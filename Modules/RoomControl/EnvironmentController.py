import time
import logging

from Modules.RoomControl.AbstractSmartDevices import AbstractToggleDevice, background

logging = logging.getLogger(__name__)


class EnvironmentControllerHost:

    def __init__(self, database, sensor_host=None, room_controllers=None):

        if room_controllers is None:
            room_controllers = []

        self.sensor_host = sensor_host

        self.database = database
        self.database_init()
        self.room_controllers = room_controllers
        self.enviv_controllers = {}

        cursor = self.database.cursor()
        cursor.execute("SELECT * FROM enviv_controllers")
        controllers = cursor.fetchall()
        for controller in controllers:
            self.enviv_controllers[controller[0]] = \
                EnvironmentController(controller[0], self.database, room_controllers=self.room_controllers,
                                      sensor_host=self.sensor_host)

    def database_init(self):
        cursor = self.database.cursor()
        cursor.execute("""CREATE TABLE IF NOT EXISTS 
                        enviv_controllers (
                        name text,
                        current_set_point integer,
                        source_name text,
                        enabled boolean
                        )""")
        cursor.execute("""CREATE TABLE IF NOT EXISTS
                        enviv_control_devices (
                        device_id text,
                        lower_delta float,
                        upper_delta float,
                        action_direction integer,
                        control_source text
                        )""")
        cursor.close()
        self.database.commit()

    def refresh_all(self):
        pass

    def get_device(self, device_id):
        for device in self.enviv_controllers.values():
            if device.name() == device_id:
                return device

    def get_all_devices(self):
        return self.enviv_controllers.values()


class EnvironmentController:

    def __init__(self, name, database, room_controllers=None, sensor_host=None):

        if room_controllers is None:
            room_controllers = []

        self.controller_name = name
        self.database = database
        self.room_controllers = room_controllers
        self.sensor_host = sensor_host

        self.online = True

        cursor = self.database.cursor()
        cursor.execute("SELECT * FROM enviv_controllers WHERE name=?", (self.controller_name,))
        controller = cursor.fetchone()
        cursor.close()
        self.current_setpoint = controller[1]
        self.source = self.sensor_host.get_sensor(controller[2])
        self.enabled = (False if controller[3] == 0 else True)

        self.devices = []
        cursor = self.database.cursor()
        cursor.execute("SELECT * FROM enviv_control_devices WHERE control_source=?", (self.controller_name,))
        devices = cursor.fetchall()
        for device in devices:
            self.devices.append(ControlledDevice(device[0], self.get_device(device[0]), self.database))

        for device in self.devices:
            device.device.auto = self.enabled

        self.periodic_check()

    def get_all_devices(self):
        return self.devices

    def get_device(self, device_name):
        for room_controller in self.room_controllers:
            if device := room_controller.get_device(device_name):
                return device
        return None

    @background
    def periodic_check(self):

        if hasattr(self.source, "get_value"):
            while True:
                if not self.source.get_fault():
                    for device in self.devices:
                        device.check(self.source.get_value(), self.current_setpoint)
                else:
                    logging.warning(f"EnvironmentController ({self.controller_name}): Source sensor is offline")
                time.sleep(30)
        else:
            logging.warning(f"EnvironmentController ({self.controller_name}): Source sensor is not a sensor")

    def get_state(self):
        value = {
            "on": self.enabled,
            "target_value": self.current_setpoint,
            "current_value": self.source.get_value(),
        }
        # logging.info(f"EnvironmentController ({self.controller_name}): State requested ({value})")
        return value

    def get_info(self):
        value = {
            "name": self.controller_name,
            "sensor": self.source.get_name(),
            "units": self.source.get_unit()
        }
        # logging.info(f"EnvironmentController ({self.controller_name}): Info requested ({value})")
        return value

    def get_health(self):
        return {
            "online": self.online,
            "fault": bool(self.source.get_fault()),
            "reason": "Unknown"
        }

    def get_type(self):
        return "environment_controller"

    def name(self):
        return self.controller_name

    def auto_state(self):
        return {"is_auto": False}

    @property
    def on(self):
        return self.enabled

    @on.setter
    def on(self, value):
        self.enabled = value

        for device in self.devices:
            device.device.auto = value

        cursor = self.database.cursor()
        cursor.execute("UPDATE enviv_controllers SET enabled=? WHERE name=?", (int(value), self.controller_name))
        cursor.close()
        self.database.commit()
        logging.info(f"EnvironmentController ({self.controller_name}): Enabled set to {value}")

    @property
    def setpoint(self):
        return self.current_setpoint

    @setpoint.setter
    def setpoint(self, value):
        value = float(value)  # Make sure it's an integer because sometimes the api sends a string
        self.current_setpoint = value
        cursor = self.database.cursor()
        cursor.execute("UPDATE enviv_controllers SET current_set_point=? WHERE name=?", (value, self.controller_name))
        cursor.close()
        self.database.commit()


class ControlledDevice:

    def __init__(self, name, device: AbstractToggleDevice, database):
        self.name = name
        self.device = device
        self.database = database

        cursor = self.database.cursor()
        cursor.execute("SELECT * FROM enviv_control_devices WHERE device_id=?", (self.name,))
        device = cursor.fetchone()
        cursor.close()
        self.control_source = device[4]
        self.action_direction = int(device[3])  # 1 if this device causes the source to increase, -1 if it causes it to decrease
        # The action direction changes what the following values do
        self.lower_hysteresis = float(device[1])  # Threshold for turning the device on if the action direction is positive and off if it is negative
        self.upper_hysteresis = float(device[2])  # Threshold for turning the device off if the action direction is positive and on if it is negative

    """
    Checks if this particular device should be on or off 
    """

    def check(self, current_value, setpoint):
        if self.action_direction == 1:  # If the action direction is positive (the device causes the source to increase)
            if self.device.on:  # If the device is on check if it should be turned off
                if current_value > setpoint + self.upper_hysteresis:  # If the current value is above the setpoint plus the upper hysteresis
                    self.device.on = False
                    logging.info(f"ControlledDevice ({self.name}): Turning off")
            else:  # If the device is off check if it should be turned on
                if current_value < setpoint + self.lower_hysteresis:  # If the current value is below the setpoint plus the lower hysteresis
                    self.device.on = True
                    logging.info(f"ControlledDevice ({self.name}): Turning on")
        else:  # If the action direction is negative (the device causes the source to decrease)
            if self.device.on:  # If the device is on check if it should be turned off
                if current_value < setpoint - self.lower_hysteresis:  # If the current value is below the setpoint minus the upper hysteresis
                    self.device.on = False
                    logging.info(f"ControlledDevice ({self.name}): Turning off")
            else:
                if current_value > setpoint - self.upper_hysteresis:
                    self.device.on = True
                    logging.info(f"ControlledDevice ({self.name}): Turning on")
