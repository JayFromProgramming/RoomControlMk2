import time

import ConcurrentDatabase
from Modules.RoomControl.API.action_handler import process_device_command
from Modules.RoomControl.API.datagrams import APIMessageRX
from Modules.RoomControl.Decorators import background
from Modules.RoomControl.OccupancyDetection.BluetoothOccupancy import BluetoothDetector

from loguru import logger as logging
from Modules.RoomControl.OccupancyDetection.OccupancyDetector import OccupancyDetector


class StateEnumerator:
    inactive = 0
    active = 1
    motion = 2
    fault = 3
    dnd = 4


class LightControllerHost:

    def __init__(self, database: ConcurrentDatabase.Database,
                 occupancy_detector: OccupancyDetector, room_controllers=None):

        logging.info("Initializing Light Controller Host")

        if room_controllers is None:
            room_controllers = []

        self.database = database
        self.database_init()
        self.room_controllers = room_controllers
        self.light_controllers = {}
        self.occupancy_detector = occupancy_detector

        table = self.database.get_table("light_controllers")
        controllers = table.get_all()

        for controller in controllers:
            self.light_controllers[controller['name']] = \
                LightController(controller['name'], self.database, self.occupancy_detector,
                                room_controllers=self.room_controllers)

        logging.info("Light Controller Host Initialized")
        self.periodic_update()

    def database_init(self):
        self.database.create_table("light_controllers",
                                   {"name": "TEXT", "active_state": "TEXT", "inactive_state": "TEXT",
                                    "enabled": "BOOLEAN", "current_state": "BOOLEAN", "door_motion_state": "TEXT",
                                    "fault_state": "TEXT"})
        self.database.create_table("light_control_devices", {"device_id": "TEXT", "control_source": "TEXT"})
        self.database.create_table("light_control_targets", {"device_uuid": "INTEGER", "control_source": "TEXT"})

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

    def __init__(self, name, database: ConcurrentDatabase.Database,
                 occupancy_detector: OccupancyDetector, room_controllers=None):
        logging.info(f"LightController: {name} is being initialised")

        if room_controllers is None:
            room_controllers = []

        self.controller_name = name
        self.database = database
        self.room_controllers = room_controllers

        self.database.update_table("light_controllers", 1,
                                   ["""alter table light_controllers add dnd_state TEXT default null"""])

        table = self.database.get_table("light_controllers")
        controller = table.get_row(name=name)

        print(controller)

        self.current_state = True if controller['current_state'] == 1 else False

        self.active_state = APIMessageRX(controller['active_state']) if controller['active_state'] is not None else None
        self.inactive_state = APIMessageRX(controller['inactive_state']) if controller[
                                                                                'inactive_state'] is not None else None
        self.door_motion_state = APIMessageRX(controller['door_motion_state']) if controller[
                                                                                      'door_motion_state'] is not None else None
        self.fault_state = APIMessageRX(controller['fault_state']) if controller['fault_state'] is not None else None
        self.dnd_state = APIMessageRX(controller['dnd_state']) if controller['dnd_state'] is not None else None
        self.enabled = True if controller['enabled'] == 1 else False

        self.online = True
        self.changing_state = False
        self.dnd_active = False

        self.occupancy_detector = occupancy_detector

        self.light_control_devices = {}
        self.light_control_targets = []

        devices_table = self.database.get_table("light_control_devices")
        devices = devices_table.get_rows(control_source=self.controller_name)

        for device in devices:
            self.light_control_devices[device['device_id']] = self._get_device(device['device_id'])

        targets_table = self.database.get_table("light_control_targets")
        targets = targets_table.get_rows(control_source=self.controller_name)

        for target in targets:
            self.light_control_targets.append(target['device_uuid'])

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
            if self.dnd_active:
                if self.dnd_state is not None:
                    self.set_state(StateEnumerator.dnd, self.dnd_state)
                    return
            # If the state isn't already on or motion
            if self.current_state != StateEnumerator.inactive and self.current_state != StateEnumerator.motion:
                if self.occupancy_detector.bluetooth_offline():  # If the bluetooth detector has faulted
                    if self.fault_state is not None:  # If there is a fault state to go to
                        self.set_state(StateEnumerator.fault, self.fault_state)  # Set the state to fault
            if self.current_state != StateEnumerator.active:  # If the state is off or faulted
                if self.occupancy_detector.was_activity_recent():  # If there was activity in the room recently
                    if self.door_motion_state is not None:
                        self.set_state(StateEnumerator.motion, self.door_motion_state)
            if not self.occupancy_detector.bluetooth_offline():  # If the bluetooth detector has faulted
                if self._check_occupancy():
                    self.set_state(StateEnumerator.active, self.active_state)
                elif not self.occupancy_detector.was_activity_recent():
                    self.set_state(StateEnumerator.inactive, self.inactive_state)
        elif self.changing_state:
            logging.info(f"LightController: {self.controller_name} is changing state")

    @background
    def set_state(self, state_val, state=None):
        prev_state = self.current_state
        try:
            if self.current_state != state_val:
                self.changing_state = True
                self.current_state = state_val
                logging.info(f"LightController: {self.controller_name} is changing state to {state_val}")
                # Use the API action_handler method to process the state change
                for device in self.light_control_devices.values():
                    if device is None:
                        raise ValueError(f"Device ({device}) not found")
                    else:  # Device found
                        for key, value in state.__dict__.items():  # Loop through all attributes in the message
                            if hasattr(device, key):  # Check the device has an attribute with the same name
                                setattr(device, key, value)
                self.changing_state = False
                time.sleep(5)
                logging.info(f"Validating state change for {self.controller_name}")
                # Validate the state change
                for device in self.light_control_devices.values():
                    if device is None:
                        raise ValueError(f"Device ({device}) not found")
                    else:
                        for key, value in state.__dict__.items():
                            if hasattr(device, key):
                                if isinstance(getattr(device, key), tuple):
                                    # If the attribute is a tuple then cast it to a list for comparison
                                    if list(getattr(device, key)) != list(value):
                                        logging.error(f"LightController: {self.controller_name} failed to change "
                                                      f"state to {state_val}")
                                        logging.error(f"LightController: {self.controller_name} failed to change {key}"
                                                      f" to {value} current value is "
                                                      f"{getattr(device, key)}")
                                        self.current_state = prev_state
                                elif getattr(device, key) != value:
                                    logging.error(f"LightController: {self.controller_name} failed to change state"
                                                  f" to {state_val}")
                                    logging.error(f"LightController: {self.controller_name} failed to change {key} "
                                                  f"to {value} current value is "
                                                  f"{getattr(device, key)}")
                                    self.current_state = prev_state
        except Exception as e:
            logging.error(f"LightController: {self.controller_name} failed to change state to {state_val} due to {e}")
            self.current_state = prev_state
            self.changing_state = False

    def get_state(self):
        return {
            "on": self.enabled,
            "dnd_active": self.dnd_active,
            "current_state": self.current_state
        }

    def get_info(self):
        return {
            "name": self.controller_name,
            "active_state": self.active_state.__str__(),
            "inactive_state": self.inactive_state.__str__(),
            "dnd_state": self.dnd_state.__str__(),
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
            "fault": self.occupancy_detector.bluetooth_offline(),
            "reason": "Bluetooth Offline" if self.occupancy_detector.bluetooth_offline() else "Unknown"
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
        self.changing_state = False
        self.current_state = StateEnumerator.inactive
        table = self.database.get_table("light_controllers")
        row = table.get_row(name=self.controller_name)
        row.set(enabled=value)
        # Set all the assigned devices .is_auto to value
        for device in self.light_control_devices.values():
            if hasattr(device, "is_auto"):
                device.is_auto = value
            else:
                logging.warning(f"Device {device} does not have is_auto attribute")

    @property
    def enable_dnd(self):
        return self.dnd_state is not None

    @enable_dnd.setter
    def enable_dnd(self, value):
        self.dnd_active = value
        self.update()

    def set_on(self, value):
        self.on = value
