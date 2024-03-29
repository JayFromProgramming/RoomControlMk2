import time
from loguru import logger as logging

import ConcurrentDatabase
from Modules.RoomControl.AbstractSmartDevices import AbstractToggleDevice
from Modules.RoomControl.Decorators import background, api_action


class EnvironmentControllerHost:

    def __init__(self, database: ConcurrentDatabase.Database,
                 sensor_host=None, room_controllers=None):

        if room_controllers is None:
            room_controllers = []

        self.sensor_host = sensor_host

        self.database = database
        self.database_init()
        self.room_controllers = room_controllers
        self.enviv_controllers = {}

        table = self.database.get_table("enviv_controllers")
        controllers = table.get_all()

        for controller in controllers:
            self.enviv_controllers[controller['name']] = \
                EnvironmentController(controller['name'], self.database,
                                      room_controllers=self.room_controllers,
                                      sensor_host=self.sensor_host)

    def database_init(self):
        # cursor = self.database.cursor()
        # cursor.execute("""CREATE TABLE IF NOT EXISTS
        #                 enviv_controllers (
        #                 name text,
        #                 current_set_point integer,
        #                 source_name text,
        #                 enabled boolean
        #                 )""")
        self.database.create_table("enviv_controllers", {"name": "TEXT", "current_set_point": "INTEGER",
                                                         "source_name": "TEXT", "enabled": "BOOLEAN"},
                                   primary_keys=["name"])
        # cursor.execute("""CREATE TABLE IF NOT EXISTS
        #                 enviv_control_devices (
        #                 device_id text,
        #                 lower_delta float,
        #                 upper_delta float,
        #                 action_direction integer,
        #                 control_source text
        #                 )""")
        self.database.create_table("enviv_control_devices", {"device_id": "TEXT", "lower_delta": "FLOAT",
                                                             "upper_delta": "FLOAT", "action_direction": "INTEGER",
                                                             "control_source": "TEXT"},
                                   primary_keys=["device_id", "control_source"])
        # cursor.close()
        # self.database.commit()

    def refresh_all(self):
        pass

    def get_device(self, device_id):
        for device in self.enviv_controllers.values():
            if device.name() == device_id:
                return device

    def get_all_devices(self):
        return self.enviv_controllers.values()


class EnvironmentController:

    def __init__(self, name, database: ConcurrentDatabase.Database,
                 room_controllers=None, sensor_host=None):

        if room_controllers is None:
            room_controllers = []

        self.controller_name = name
        self.database = database
        self.room_controllers = room_controllers
        self.sensor_host = sensor_host

        self.online = True
        self._reason = "Unknown"

        table = self.database.get_table("enviv_controllers")
        self.controller_entry = table.get_row(name=self.controller_name)
        self.current_setpoint = self.controller_entry['current_set_point']
        self.source = self.sensor_host.get_sensor(self.controller_entry['source_name'])
        self.enabled = (False if self.controller_entry['enabled'] == 0 else True)

        self.devices = []
        table = self.database.get_table("enviv_control_devices")
        devices = table.get_rows(control_source=self.controller_name)
        self._fault = False

        for device in devices:
            self.devices.append(ControlledDevice(device['device_id'], self.get_device(device['device_id']), self.database))

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
                if self.enabled:
                    if not self.source.get_fault():
                        for device in self.devices:
                            device.fault = False
                            device.check(self.source.get_value(), self.current_setpoint)
                        self._fault = False
                        self._reason = "Unknown"
                    elif self.all_controlled_devices_down():
                        self._fault = True
                        self._reason = "No working devices"
                    else:
                        logging.warning(f"EnvironmentController ({self.controller_name}): Source sensor is offline")
                        for device in self.devices:
                            if not device.fault:
                                device.fault = True
                                device.fault_encountered()
                        self._reason = "Source is offline"
                time.sleep(30)
        else:
            logging.warning(f"EnvironmentController ({self.controller_name}): Source sensor is not a sensor")
            self._reason = "Source is not a sensor"

    def get_value(self):
        return self.setpoint

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
            "reason": self.source.get_reason() if self.source.get_fault() else self._reason
        }

    def all_controlled_devices(self):
        return self.devices

    def all_controlled_devices_down(self):
        for device in self.devices:
            if not device.device.online or not device.device.fault:
                return False
        return True

    @staticmethod
    def get_type():
        return "environment_controller"

    def name(self):
        return self.controller_name

    def auto_state(self):
        return {"is_auto": self.enabled}

    @property
    def on(self):
        return self.enabled

    @on.setter
    def on(self, value):
        self.enabled = value

        for device in self.devices:
            device.device.auto = value

        # cursor = self.database.cursor()
        # cursor.execute("UPDATE enviv_controllers SET enabled=? WHERE name=?", (int(value), self.controller_name))
        # cursor.close()
        # self.database.commit()

        self.controller_entry.set(enabled=value)

        logging.info(f"EnvironmentController ({self.controller_name}): Enabled set to {value}")

    @property
    def setpoint(self):
        return self.current_setpoint

    @setpoint.setter
    def setpoint(self, value):
        value = float(value)  # Make sure it's an integer because sometimes the api sends a string
        self.current_setpoint = value
        # cursor = self.database.cursor()
        # cursor.execute("UPDATE enviv_controllers SET current_set_point=? WHERE name=?", (value, self.controller_name))
        # cursor.close()
        # self.database.commit()

        self.controller_entry.set(current_set_point=value)

    @property
    def target_value(self):
        return self.setpoint

    @target_value.setter
    def target_value(self, value):
        self.setpoint = value

    @property
    def current_value(self):
        return round(self.source.get_value(), 2)

    @property
    def fault(self):
        return self.source.get_fault()

    @property
    def unit(self):
        return self.source.get_unit()


class ControlledDevice:

    def __init__(self, name, device: AbstractToggleDevice, database: ConcurrentDatabase.Database):
        self.name = name
        self.device = device
        self.database = database

        table = self.database.get_table("enviv_control_devices")
        device = table.get_row(device_id=self.name)

        self.control_source = device['control_source']  # The name of the controller that controls this device
        self.action_direction = int(device['action_direction'])
        self.lower_hysteresis = float(device['lower_delta'])
        self.upper_hysteresis = float(device['upper_delta'])
        self.fault = False

    def check(self, current_value, setpoint):
        """
        Checks if this particular device should be on or off
        """
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
                if current_value < setpoint + self.lower_hysteresis:  # If the current value is below the setpoint minus the upper hysteresis
                    self.device.on = False
                    logging.info(f"ControlledDevice ({self.name}): Turning off")
            else:
                if current_value > setpoint + self.upper_hysteresis:
                    self.device.on = True
                    logging.info(f"ControlledDevice ({self.name}): Turning on")

    @background
    def fault_encountered(self):
        """
        Called when the temperature sensor encounters a fault
        The device will be turned off and will not be turned on until the fault is resolved
        or the device is manually turned on
        """
        while self.fault:
            if self.device.auto:
                if self.device.on:
                    self.device.on = False
                self.device.fault = True
                self.device.offline_reason = "SRC CTLR SENSOR FAULT"
            time.sleep(1)
