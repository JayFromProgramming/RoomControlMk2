import time

from Modules.RoomControl.API.datagrams import APIMessageRX
from Modules.RoomControl.AbstractSmartDevices import background
from Modules.RoomControl.OccupancyDetection.BluetoothOccupancy import BluetoothDetector

import logging

logging = logging.getLogger(__name__)


class LightControllerHost:

    def __init__(self, database, bluetooth_occupancy: BluetoothDetector, room_controllers=None):

        logging.info("Initializing Light Controller Host")

        if room_controllers is None:
            room_controllers = []

        self.database = database
        self.database_init()
        self.room_controllers = room_controllers
        self.light_controllers = {}
        self.bluetooth_occupancy = bluetooth_occupancy

        cursor = self.database.cursor()
        self.database.lock.acquire()
        cursor.execute("SELECT * FROM light_controllers")
        controllers = cursor.fetchall()
        cursor.close()
        self.database.lock.release()
        for controller in controllers:
            self.light_controllers[controller[0]] = \
                LightController(controller[0], self.database, self.bluetooth_occupancy, room_controllers=self.room_controllers,
                                active_state=controller[1], inactive_state=controller[2], enabled=controller[3], current_state=controller[4])

        logging.info("Light Controller Host Initialized")
        self.periodic_update()

    def database_init(self):
        cursor = self.database.cursor()
        cursor.execute("""CREATE TABLE IF NOT EXISTS 
                        light_controllers (
                        name text,
                        active_state text,
                        inactive_state text,
                        enabled boolean,
                        current_state boolean
                        )""")
        cursor.execute("""CREATE TABLE IF NOT EXISTS
                        light_control_devices (
                        device_id text,
                        control_source text
                        )""")
        cursor.execute("""CREATE TABLE IF NOT EXISTS
                        light_control_targets (
                        device_uuid integer,
                        control_source text
                        )""")
        cursor.close()
        self.database.commit()

    def get_all_devices(self):
        return self.light_controllers.values()

    def get_device(self, device_id):
        for device in self.light_controllers.values():
            if device.name() == device_id:
                return device

    @background
    def periodic_update(self):
        logging.info("Starting Light Controller Host Periodic Update")
        while True:
            for controller in self.light_controllers.values():
                controller.update()
            time.sleep(5)

    def refresh_all(self):
        pass


class LightController:

    def __init__(self, name, database, bluetooth_detector: BluetoothDetector, room_controllers=None,
                 active_state=None, inactive_state=None, enabled=False, current_state=False):
        logging.info(f"LightController: {name} is being initialised")

        if room_controllers is None:
            room_controllers = []

        self.controller_name = name
        self.database = database
        self.room_controllers = room_controllers

        self.active_state = APIMessageRX(active_state) if active_state else None
        self.inactive_state = APIMessageRX(inactive_state) if inactive_state else None
        self.enabled = True if enabled == 1 else False

        self.online = True
        self.current_state = True if current_state == 1 else False

        self.bluetooth_detector = bluetooth_detector

        self.light_control_devices = {}
        self.light_control_targets = []

        cursor = self.database.cursor()
        cursor.execute("SELECT * FROM light_control_devices WHERE control_source=?", (self.controller_name,))
        devices = cursor.fetchall()
        for device in devices:
            self.light_control_devices[device[0]] = self._get_device(device[0])

        cursor.execute("SELECT * FROM light_control_targets WHERE control_source=?", (self.controller_name,))
        targets = cursor.fetchall()
        for target in targets:
            self.light_control_targets.append(target[0])

        self.on = self.enabled
        logging.info(f"LightController: {name} has been initialised,"
                     f" {len(self.light_control_devices)} devices and {len(self.light_control_targets)} targets\n"
                     f"Active State: {self.active_state}\n"
                     f"Inactive State: {self.inactive_state}")

    def _get_device(self, device_name):
        for room_controller in self.room_controllers:
            if device := room_controller.get_device(device_name):
                return device
        return None

    def _check_occupancy(self):
        for target in self.light_control_targets:
            if self.bluetooth_detector.is_here(target):
                return True
        return False

    def update(self):
        if self.enabled:
            if self._check_occupancy():
                self.set_state(True, self.active_state)
            else:
                self.set_state(False, self.inactive_state)

    def set_state(self, state_bool, state=None):
        if self.current_state != state_bool:
            logging.info(f"LightController: {self.controller_name} is changing state to {state_bool}")
            self.current_state = state_bool
            for device in self.light_control_devices.values():
                if hasattr(state, "on"):
                    device.set_on(state.on)
                if hasattr(state, "brightness"):
                    device.set_brightness(state.brightness)
                if hasattr(state, "color"):
                    device.set_color(state.color)

    def get_state(self):
        return {
            "on": self.enabled,
            "current_state": self.current_state
        }

    def get_info(self):
        return {
            "name": self.controller_name,
            "active_state": self.active_state.__str__(),
            "inactive_state": self.inactive_state.__str__(),
            "targets": self.get_targets_info()
        }

    def get_targets_info(self):
        devices = {}
        for device in self.light_control_targets:
            name = self.bluetooth_detector.get_name(device)
            devices.update({name: self.bluetooth_detector.is_here(device)})
        return devices

    def get_health(self):
        return {"online": True}

    def get_type(self):
        return "light_controller"

    def auto_state(self):
        return False

    def name(self):
        return self.controller_name

    @property
    def on(self):
        return self.enabled

    @on.setter
    def on(self, value):
        self.enabled = value
        cursor = self.database.cursor()
        self.database.lock.acquire()
        cursor.execute("UPDATE light_controllers SET enabled=? WHERE name=?", (value, self.controller_name))
        cursor.close()
        self.database.lock.release()
        self.database.commit()
        # Set all the assigned devices .is_auto to value
        for device in self.light_control_devices.values():
            if hasattr(device, "is_auto"):
                device.is_auto = value
            else:
                logging.warning(f"Device {device} does not have is_auto attribute")

    def set_on(self, value):
        self.on = value
