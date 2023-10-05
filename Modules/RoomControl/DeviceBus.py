import os
from loguru import logger as logging

from Modules.RoomControl.Drivers.__driver import Driver


class DeviceBus:

    def __init__(self, database):
        self.database = database
        self.devices = {}
        self.sensors = {}
        self.drivers = {}

    def load_drivers(self):
        # Load all classes in the Drivers folder that are subclasses of Driver
        for file in os.listdir("Modules/RoomControl/Drivers"):
            if file.endswith(".py") and not file.startswith("__"):
                module_name = file[:-3]
                module = __import__(f"Modules.RoomControl.Drivers.{module_name}", fromlist=[module_name])
                for name, obj in module.__dict__.items():
                    if isinstance(obj, type) and issubclass(obj, Driver) and obj.should_load:
                        self.drivers[obj.name] = obj(self.database)
                        logging.info(f"Loaded driver {obj.name}")

    def load_devices(self):
        for driver in self.drivers.values():
            loaded = 0
            driver.wait_for_ready()
            for device in driver.devices:
                # For every device give it an attribute called "bus" which references this bus
                device.bus = self
                self.devices[device.name] = device
                loaded += 1
            logging.info(f"Loaded {loaded} devices from driver {driver.name}")

    def get_device(self, name):
        if name in self.devices:
            return self.devices[name]
        else:
            return None
