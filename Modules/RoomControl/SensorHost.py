import datetime
import logging
import time

from Modules.RoomControl.AbstractSmartDevices import background

logging = logging.getLogger(__name__)

class SensorHost:

    def __init__(self):
        self.sensors = []

        self.sensors.append(EnvironmentSensor("enviv_sensor"))

        self.start_sensor_reads()

    def start_sensor_reads(self):
        for sensor in self.sensors:
            sensor.read_sensor()  # Background task to update the sensor values

    def get_sensors(self):
        return self.sensors

    def get_sensor(self, sensor_id):
        logging.info(f"SensorHost: Searching for sensor {sensor_id}")
        for sensor in self.sensors:
            for sensor_value in sensor.get_values():
                if sensor_value.get_name() == sensor_id:
                    return sensor_value


class SensorValue:

    def __init__(self, name=None, value=None, unit=None, rolling_average=False, rolling_average_length=None):
        self.name = name  # Name of the value
        self.value = value  # type: float or int or str or bool
        self.unit = unit  # type: str
        self.roll_avg = rolling_average  # type: bool
        self.roll_avg_len = rolling_average_length  # type: int
        self.roll_avg_values = []  # type: list
        self._fault = False  # type: bool

    def get_value(self):
        return self.value

    def get_unit(self):
        return self.unit

    def get_name(self):
        return self.name

    def set_value(self, value):

        if len(self.roll_avg_values) >= 3:
            # Cap the incoming value to no more than 2 units above/below the current value (to prevent spikes)
            value = min(self.value + 2, value)
            value = max(self.value - 2, value)

        if self.roll_avg:
            self.roll_avg_values.append(value)
            if len(self.roll_avg_values) > self.roll_avg_len:
                self.roll_avg_values.pop(0)
            self.value = sum(self.roll_avg_values) / len(self.roll_avg_values)  # type: float
        else:
            self.value = value

    def set_fault(self, fault):
        # logging.warning(f"SensorValu/e ({self.name}): Setting fault to {fault}")
        self._fault = fault

    def get_fault(self):
        return self._fault


class Sensor:

    def __init__(self, name):
        self.name = name
        self.values = {}  # type: dict[str, SensorValue]
        self.last_updated = None  # Last time the sensor was updated
        self.fault = False  # If the sensor is faulty, this will be set to True

    def get_values(self):
        return self.values.values()

    def get_value(self, name):
        return self.values[name].get_value()

    def get_last_updated(self):
        return self.last_updated

    def read_sensor(self):
        raise NotImplementedError


def convert_cel_to_fahr(cel):
    return round(cel * 9 / 5 + 32, 2)


class EnvironmentSensor(Sensor):

    def __init__(self, name):
        super().__init__(name)
        self.values["temperature"] = SensorValue("room_temp", 0, "°F", True, 5)
        self.values["humidity"] = SensorValue("room_humid", 0, "%", True, 5)
        try:  # If the controller is not running on a Raspberry Pi, this will fail
            logging.info(f"EnvironmentSensor ({self.name}): Initialising DHT22 sensor")
            import Adafruit_DHT
            self.adafruit_library = Adafruit_DHT
            self.dht_sensor = Adafruit_DHT.DHT22
        except ImportError as e:
            logging.error(f"EnvironmentSensor ({self.name}): DHT22 sensor could not be initialised - {e}")
            self.adafruit_library = None
            self.dht_sensor = None

        # self.read_sensor()

    @property
    def fault(self):
        return self._fault

    @fault.setter
    def fault(self, set_value: bool):
        self._fault = set_value
        for value in self.values.values():
            value.set_fault(set_value)

    @background
    def read_sensor(self):
        # Read the sensor and set the value and last_updated
        logging.info(f"EnvironmentSensor ({self.name}): Starting background update task")
        while True:
            if self.adafruit_library is not None:
                try:
                    # logging.info(f"EnvironmentSensor ({self.name}): Reading sensor")
                    humidity, temperature = self.adafruit_library.read_retry(self.dht_sensor, 4)
                    if humidity == 0 and temperature == 0:
                        logging.warning(f"EnvironmentSensor ({self.name}): Sensor returned 0")
                        self.fault = True

                    elif humidity is None or temperature is None:
                        logging.warning(f"EnvironmentSensor ({self.name}): Sensor returned None")
                        self.fault = True

                    else:
                        self.values["temperature"].set_value(convert_cel_to_fahr(temperature))
                        self.values["humidity"].set_value(round(humidity, 2))
                        self.last_updated = datetime.datetime.now()
                        # logging.info(f"EnvironmentSensor ({self.name}): Sensor read successful")
                        self.fault = False
                except RuntimeError as error:
                    self.fault = True
                    logging.error(f"EnvironmentSensor ({self.name}): DHT22 sensor read failed - {error}")
                    print(error.args[0])
            else:
                self.fault = True
                logging.error(f"EnvironmentSensor ({self.name}): DHT22 sensor read failed "
                              f"- DHT22 sensor not initialised")
                break  # If the sensor is not initialised, stop trying to read it
            # Wait 5 seconds before reading again
            time.sleep(20)
