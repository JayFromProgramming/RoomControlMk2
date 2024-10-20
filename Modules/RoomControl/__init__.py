import json
import socket
import subprocess
import sys

import netifaces as netifaces
from loguru import logger as logging
import sqlite3
import threading
import os
import time

from ConcurrentDatabase.Database import Database
# from Modules.RoomControl import MagicHueAPI, VeSyncAPI, VoiceMonkeyAPI
# from Modules.RoomControl.API.net_api import NetAPI
from Modules.RoomControl.Decorators import background

# Auto import modules that are in Modules/RoomControl that have a class that inherits RoomModule
# This is done to make sure that all modules are dynamically loaded
from Modules.RoomModule import RoomModule
from Modules.RoomObject import RoomObject

for module in os.listdir("Modules/RoomControl"):
    if module.endswith(".py") and module != "__init__.py":
        module_name = module.replace(".py", "")
        logging.info(f"Importing {module_name}")
        try:
            __import__(f"Modules.RoomControl.{module_name}", fromlist=[module_name])
        except Exception as e:
            logging.error(f"Error importing {module_name}: {e}")
            logging.exception(e)
    if os.path.isdir(f"Modules/RoomControl/{module}"):
        logging.info(f"Importing {module}")
        for module_file in os.listdir(f"Modules/RoomControl/{module}"):
            if module_file.endswith(".py") and module_file != "__init__.py":
                module_name = module_file.replace(".py", "")
                logging.info(f"Importing {module_name} from {module}")
                __import__(f"Modules.RoomControl.{module}.{module_name}", fromlist=[module_name])

def get_local_ip():
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    raise NotImplementedError


def database_backup(status, remaining, total):
    if remaining == 0:
        logging.info(f"Database backup complete, {total} pages backed up")
    else:
        logging.info(f"Database backup {status}, {remaining} pages remaining")


class ObjectPointer:

    def __init__(self, initial_ref):
        self.reference = initial_ref

    def __getattr__(self, item):
        # Pass the attribute request to the reference object unless we are trying to update the reference
        if item == "reference":
            return self.reference
        return getattr(self.reference, item)

    def __setattr__(self, key, value):
        if key == "reference":
            super(ObjectPointer, self).__setattr__(key, value)
        else:
            setattr(self.reference, key, value)


class RoomController:

    def __init__(self, db_path: str = "room_data.db"):
        self.database = Database(db_path)
        try:
            self.backup_database = sqlite3.connect(f"{db_path}.bak")
            self.database.backup(target=self.backup_database, progress=database_backup)
        except sqlite3.OperationalError:
            logging.warning("Backup database is already in use, skipping backup")
        self.init_database()

        # Find all subclasses of RoomModule and create an instance of them
        self.controllers = []
        self.room_objects = []
        for room_module in RoomModule.__subclasses__():
            logging.info(f"Creating instance of {room_module.__name__}")
            # if room_module.__name__ != "SatelliteInterface":
            #     continue
            try:
                room_module(self)
            except Exception as e:
                logging.error(f"Error creating instance of {room_module.__name__}: {e}")
                logging.exception(e)

    def init_database(self):
        # cursor = self.database.cursor()
        # cursor.execute('''CREATE TABLE IF NOT EXISTS auto_lights (device_id TEXT, is_auto BOOLEAN, current_mode TEXT)''')
        self.database.create_table("auto_lights", {"device_id": "TEXT", "is_auto": "BOOLEAN", "current_mode": "TEXT"})
        # cursor.execute('''CREATE TABLE IF NOT EXISTS secrets (secret_name TEXT, secret_value TEXT)''')
        self.database.create_table("secrets", {"secret_name": "TEXT", "secret_value": "TEXT"})
        # self.database.commit()

    def refresh(self):
        # logging.info("Refreshing devices")

        for controller in self.controllers:
            if hasattr(controller, "refresh_all"):
                controller.refresh_all()

    def _create_promise_object(self, device_name, device_type="promise"):
        # If a room object was looking for another object that hasn't been created yet, it will get a empty RoomObject
        # That will be replaced with the real object when it is created later this allows for circular dependencies
        logging.info(f"Creating promise object {device_name} of type {device_type}")
        pointer = ObjectPointer(RoomObject(device_name, device_type))
        return pointer

    def _create_promise_module(self, module_name):
        logging.info(f"Creating promise module {module_name}")
        return RoomModule(self, module_name)

    def attach_module(self, room_module):
        self.controllers.append(room_module)

    def attach_object(self, device: RoomObject):
        if not issubclass(type(device), RoomObject):
            raise TypeError(f"Device {device} is not a subclass of RoomObject")
        # Check if the device exists as a promise object and replace it with the real object without changing the
        # reference So that any references to the promise object are updated to the real object
        for i, room_object in enumerate(self.room_objects):
            if room_object.object_name == device.object_name:
                logging.info(f"Replacing promise object {room_object.object_name} with real object")
                # Make sure that we copy the callbacks from the promise object to the real object
                device._callbacks = room_object._callbacks
                self.room_objects[i].reference = device  # Replace the promise object with the real object
                return
        logging.info(f"Attaching object {device.object_name} to room controller")
        self.room_objects.append(device)

    def get_all_devices(self):
        return self.room_objects

    def get_module(self, module_name):
        for module in self.controllers:
            if module.__class__.__name__ == module_name:
                return module
        return None

    def get_modules(self):
        return self.controllers

    def get_object(self, device_name, create_if_not_found=True):
        for device in self.room_objects:
            if device.object_name == device_name:
                return self.room_objects[self.room_objects.index(device)]  # Return the reference to the object
        if create_if_not_found:
            self.room_objects.append(self._create_promise_object(device_name))
            return self.room_objects[-1]
        return None

    def get_all_objects(self):
        return self.room_objects

    def get_type(self, device_type):
        devices = []
        for device in self.room_objects:
            if device.object_type == device_type:
                devices.append(device)
        return devices

    @background
    def background(self):
        while True:
            time.sleep(15)
