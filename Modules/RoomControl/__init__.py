import json
import multiprocessing
import re
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



logging.info("Imports complete")


def get_local_ip():
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    raise NotImplementedError


last_backup_percent = 0


def database_backup(status, remaining, total):
    global last_backup_percent
    if total == 0:
        return
    percent = (total - remaining) / total * 100
    if percent - last_backup_percent > 10:
        last_backup_percent = percent
        logging.info(f"Database backup {status}, {remaining} pages remaining, {percent:.2f}% complete")
    if remaining == 0:
        logging.info(f"Database backup complete, {total} pages backed up")


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
    # Debugging variables to exclude or only load certain modules on the test server
    exclude_modules = []
    only_modules = ["SatelliteInterface", "GoveeAPI"]

    required_modules = ["NetAPI", "SceneController"]

    def __init__(self, db_path: str = "room_data.db"):
        self.is_not_main = False

        # Validate that this is the main process, if not abort
        logging.info(f"Current process: {multiprocessing.current_process().name}")
        if multiprocessing.current_process().name != "MainProcess":
            logging.info("Not the main process, aborting")
            self.is_not_main = True
            return

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

        logging.info("Starting RoomController")
        self.database = Database(db_path)
        # self.backup_database(db_path)
        # Enable WAL mode
        self.database.execute("PRAGMA journal_mode=WAL")
        # self.load_database(self.database, db_path)
        self.init_database()
        # self.background_database_sync()
        # Find all subclasses of RoomModule and create an instance of them
        self.controllers = []
        self.room_objects = []
        for room_module in RoomModule.__subclasses__():
            logging.info(f"Creating instance of {room_module.__name__}")
            if sys.platform != "linux":
                if (len(self.only_modules) > 0 and room_module.__name__ not in self.only_modules
                        and room_module.__name__ not in self.required_modules):
                    logging.info(f"Skipping {room_module.__name__} because it is not in only_modules")
                    continue
                elif room_module.__name__ in self.exclude_modules:
                    logging.info(f"Skipping {room_module.__name__} because it is in exclude_modules")
                    continue
            try:
                room_module(self)
            except RuntimeError as e:
                logging.warning(f"Likely multiprocessing error, this can be safely ignored: {e}")
            except Exception as e:
                logging.error(f"Error creating instance of {room_module.__name__}: {e}")
                logging.exception(e)

    @background
    def backup_database(self, db_path: str = "room_data.db"):
        try:
            logging.info(f"Creating backup database at {db_path}.bak")
            backup_database = sqlite3.connect(f"{db_path}.bak")
            last_backup_percent = 0
            self.database.backup(target=backup_database, pages=1000,
                                 progress=database_backup)
        except sqlite3.OperationalError:
            logging.warning("Backup database is already in use, skipping backup")

    def load_database(self, target, source: str):
        logging.info(f"Loading database from {source}")
        target_cursor = target.cursor()
        target_cursor.execute("ATTACH DATABASE ? AS disk", (source,))
        target_cursor.execute("SELECT name FROM disk.sqlite_master WHERE type='table'")
        tables = target_cursor.fetchall()
        for table in tables:
            table = table[0]
            if table == "sqlite_sequence":
                target.execute(f"INSERT INTO {table} SELECT * FROM disk.{table}")
            else:
                target.execute(f"CREATE TABLE IF NOT EXISTS {table} AS SELECT * FROM disk.{table}")
        target.commit()

    @background
    def background_database_sync(self):
        """
        Copy the memory database to the disk database every minute
        :return:
        """
        logging.info("Starting background database sync")
        time.sleep(60)
        while True:
            try:
                logging.info("Syncing database")
                self.database.backup(target=self.disk_database, progress=database_backup)
            except Exception as e:
                logging.error(f"Error syncing database: {e}")
                logging.exception(e)
            else:
                logging.info("Database sync complete")
            finally:
                time.sleep(60)

    def init_database(self):
        # cursor = self.database.cursor()
        # cursor.execute('''CREATE TABLE IF NOT EXISTS auto_lights (device_id TEXT, is_auto BOOLEAN, current_mode TEXT)''')
        self.database.create_table("auto_lights", {"device_id": "TEXT", "is_auto": "BOOLEAN", "current_mode": "TEXT"})
        # cursor.execute('''CREATE TABLE IF NOT EXISTS secrets (secret_name TEXT, secret_value TEXT)''')
        self.database.create_table("secrets", {"secret_name": "TEXT", "secret_value": "TEXT"})
        # self.database.commit()

    def refresh(self):
        if self.is_not_main:
            return
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

    # @background
    # def background(self):
    #     while True:
    #         time.sleep(15)
