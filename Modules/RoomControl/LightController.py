import time

from Modules.RoomControl.API.datagrams import APIMessageRX
from Modules.RoomControl.AbstractSmartDevices import background
from Modules.RoomControl.OccupancyDetection.BluetoothOccupancy import BluetoothDetector

import logging

from Modules.RoomControl.OccupancyDetection.OccupancyDetector import OccupancyDetector

logging = logging.getLogger(__name__)


class LightControllerHost:

    def __init__(self, database, occupancy_detector: OccupancyDetector, room_controllers=None):

        logging.info("Initializing Light Controller Host")

        if room_controllers is None:
            room_controllers = []

        self.database = database
        self.database_init()
        self.room_controllers = room_controllers
        self.light_controllers = {}
        self.occupancy_detector = occupancy_detector

        cursor = self.database.cursor()
        self.database.lock.acquire()
        cursor.execute("SELECT * FROM light_controllers")
        controllers = cursor.fetchall()
        cursor.close()
        self.database.lock.release()
        for controller in controllers:
            self.light_controllers[controller[0]] = \
                LightController(controller[0], self.database, self.occupancy_detector, room_controllers=self.room_controllers)

        logging.info("Light Controller Host Initialized")
        self.periodic_update()

    def database_init(self):
        cursor = self.database.cursor()
        cursor.execute("""CREATE TABLE IF NOT EXISTS 
                        light_controllers (
                        name text,
                        active_state text NOT NULL,
                        inactive_state text NOT NULL,
                        enabled boolean DEFAULT TRUE,
                        current_state integer DEFAULT 0,
                        door_motion_state TEXT DEFAULT null,
                        fault_state TEXT DEFAULT null
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

    def __init__(self, name, database, occupancy_detector: OccupancyDetector, room_controllers=None):
        logging.info(f"LightController: {name} is being initialised")

        if room_controllers is None:
            room_controllers = []

        self.controller_name = name
        self.database = database
        self.room_controllers = room_controllers

        cursor = self.database.cursor()
        cursor.execute("SELECT * FROM light_controllers WHERE name=?", (name,))
        controller = cursor.fetchone()
        cursor.close()

        self.enabled = True if controller[3] == 1 else False
        self.current_state = True if controller[4] == 1 else False

        self.active_state = APIMessageRX(controller[1]) if controller[1] is not None else None
        self.inactive_state = APIMessageRX(controller[2]) if controller[2] is not None else None
        self.door_motion_state = APIMessageRX(controller[5]) if controller[5] is not None else None
        self.fault_state = APIMessageRX(controller[6]) if controller[6] is not None else None
        self.enabled = True if controller[3] == 1 else False

        self.online = True
        self.changing_state = False
        self.current_state = controller[4]

        self.occupancy_detector = occupancy_detector

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
                     f" {len(self.light_control_devices)} devices and {len(self.light_control_targets)} targets")

    def _get_device(self, device_name):
        for room_controller in self.room_controllers:
            if device := room_controller.get_device(device_name):
                return device
        return None

    def _check_occupancy(self):
        for target in self.light_control_targets:
            if self.occupancy_detector.is_here(target):
                return True
        return False

    def update(self):
        if self.enabled and not self.changing_state:
            if self.current_state != 1 and self.current_state != 2:  # If the state isn't already on or motion
                if self.occupancy_detector.bluetooth_fault():  # If the bluetooth detector has faulted
                    if self.fault_state is not None:  # If there is a fault state to go to
                        self.set_state(3, self.fault_state)  # Set the state to fault
            if self.current_state != 1:  # If the state is off or faulted
                if self.occupancy_detector.was_activity_recent():  # If there was activity in the room recently
                    if self.door_motion_state is not None:
                        self.set_state(2, self.door_motion_state)
            if not self.occupancy_detector.bluetooth_fault():  # If the bluetooth detector has faulted
                if self._check_occupancy():
                    self.set_state(1, self.active_state)
                elif not self.occupancy_detector.was_activity_recent():
                    self.set_state(0, self.inactive_state)

    @background
    def set_state(self, state_val, state=None):
        prev_state = self.current_state
        try:
            if self.current_state != state_val:
                self.changing_state = True
                self.current_state = state_val
                logging.info(f"LightController: {self.controller_name} is changing state to {state_val}")
                for device in self.light_control_devices.values():
                    if hasattr(state, "on"):
                        device.set_on(state.on)
                    if hasattr(state, "brightness"):
                        device.set_brightness(state.brightness)
                    if hasattr(state, "color"):
                        device.set_color(state.color)
                    if hasattr(state, "white"):
                        device.set_white(state.white)
                time.sleep(5)
                # Verify the light properly changed state to the desired state
                for device in self.light_control_devices.values():
                    if hasattr(state, "on"):
                        if device.get_on() != state.on:
                            logging.error(f"LightController: {self.controller_name}"
                                          f" failed to change state to [{state_val}]"
                                          f" [{device.get_on()} != {state.on}]")
                            self.current_state = prev_state
                            return
                    if hasattr(state, "brightness"):
                        if device.get_brightness() != state.brightness:
                            logging.error(f"LightController: {self.controller_name}"
                                          f" failed to change state to [{state_val}] "
                                          f"[{device.get_brightness()} != {state.brightness}]")
                            self.current_state = prev_state
                            return
                    if hasattr(state, "color"):
                        if list(device.get_color()) != state.color:
                            logging.error(f"LightController: {self.controller_name}"
                                          f" failed to change state to [{state_val}]"
                                          f" [{device.get_color()} != {state.color}]")
                            self.current_state = prev_state
                            return
                    if hasattr(state, "white"):
                        if device.get_brightness() != state.white:
                            logging.error(f"LightController: {self.controller_name}"
                                          f" failed to change state to [{state_val}] "
                                          f"[{device.get_brightness()} != {state.white}]")
                            self.current_state = prev_state
                            return
                logging.info(f"LightController: {self.controller_name} successfully changed state to {state_val}")
                self.changing_state = False
        except Exception as e:
            logging.error(f"LightController: {self.controller_name} failed to change state to {state_val} due to {e}")
            self.current_state = prev_state
            self.changing_state = False

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
            name = self.occupancy_detector.get_name(device)
            devices.update({name: self.occupancy_detector.is_here(device)})
        return devices

    def get_health(self):
        return {
            "online": True,
            "fault": self.occupancy_detector.bluetooth_fault(),
            "reason": "Bluetooth Offline" if self.occupancy_detector.bluetooth_fault() else "Unknown"
        }

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
