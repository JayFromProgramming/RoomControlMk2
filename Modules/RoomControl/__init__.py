import json
import socket

import netifaces as netifaces
from loguru import logger as logging
import sqlite3
import threading
import os
import time

from Modules.RoomControl import MagicHueAPI, VeSyncAPI, VoiceMonkeyAPI
from Modules.RoomControl.API.net_api import NetAPI
from Modules.RoomControl.AbstractSmartDevices import background
from Modules.RoomControl.CommandController import CommandController
from Modules.RoomControl.DataLogger import DataLoggingHost
from Modules.RoomControl.EnvironmentController import EnvironmentControllerHost
from Modules.RoomControl.LightController import LightControllerHost
from Modules.RoomControl.OccupancyDetection import OccupancyDetector
from Modules.RoomControl.OccupancyDetection.BluetoothOccupancy import BluetoothDetector
from Modules.RoomControl.SceneController import SceneController
from Modules.RoomControl.SensorHost import SensorHost


def get_host_names():
    """
    Gets all the ip addresses that can be bound to
    """
    interfaces = []
    for interface in netifaces.interfaces():
        try:
            if netifaces.AF_INET in netifaces.ifaddresses(interface):
                for link in netifaces.ifaddresses(interface)[netifaces.AF_INET]:
                    if link["addr"] != "":
                        interfaces.append(link["addr"])
        except Exception as e:
            logging.debug(f"Error getting interface {interface}: {e}")
            pass
    return interfaces


def check_interface_usage(port):
    """
    Returns a list of interfaces that are currently not being used
    :return:
    """
    interfaces = get_host_names()
    for interface in interfaces:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.bind((interface, port))
            s.close()
        except OSError:
            logging.warning(f"Interface {interface}:{port} was already in use")
            interfaces.remove(interface)
    return interfaces


class CustomLock:

    def __init__(self):
        self.lock = threading.Lock()
        self.lock_count = 0
        self.queued_lock_count = 0

    def acquire(self, blocking=True, timeout=-1):
        self.lock_count += 1
        logging.debug(f"Acquiring lock #{self.lock_count} (Queued: {self.queued_lock_count})")
        self.queued_lock_count += 1
        acquired = self.lock.acquire(blocking, timeout)
        if acquired:
            logging.debug(f"Acquired lock #{self.lock_count}")
            return True
        else:
            logging.debug(f"Failed to acquire lock #{self.lock_count}")
            self.queued_lock_count -= 1
            return False

    def release(self):
        logging.debug(f"Releasing lock #{self.lock_count} (Queued: {self.queued_lock_count})")
        self.queued_lock_count -= 1
        self.lock.release()


class ConcurrentDatabase(sqlite3.Connection):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.lock = CustomLock()

    def run(self, sql, *args, **kwargs):
        self.lock.acquire()
        cursor = super().cursor()
        cursor.execute(sql, *args)
        if kwargs.get("commit", True):
            try:
                super().commit()
            except sqlite3.OperationalError as e:
                logging.info(f"Database Error: Commit failed {e}")
        self.lock.release()
        return cursor

    def run_many(self, sql, *args, **kwargs):
        self.lock.acquire()
        cursor = super().cursor()
        cursor.executemany(sql, *args)
        if kwargs.get("commit", True):
            try:
                super().commit()
            except sqlite3.OperationalError as e:
                logging.info(f"Database Error: Commit failed {e}")
        self.lock.release()
        return cursor

    def get(self, sql, *args):
        cursor = self.run(sql, *args)
        result = cursor.fetchall()
        cursor.close()
        return result

    def create_table(self, table_name, columns: dict):
        self.run(f"CREATE TABLE IF NOT EXISTS {table_name} ({', '.join([f'{column} {columns[column]}' for column in columns])})")

    def update_table(self, table_name, columns):
        # TODO: Implement
        pass

    def insert(self, table_name, columns: dict, commit=True):
        """
        Inserts a row into a table
        :param table_name: The name of the table to insert into
        :param columns:  A dictionary of column names and values to insert
        :param commit:  Whether to commit the changes to the database
        :return:
        """
        self.run(f"INSERT INTO {table_name} ({', '.join(columns.keys())}) VALUES ({', '.join(['?' for _ in columns])})",
                 tuple(columns.values()), commit=commit)

    def insert_many(self, table_name, columns: list, commit=True):
        """
        Inserts multiple rows into a table
        :param table_name: The name of the table to insert into
        :param columns:  A list of dictionaries, each dictionary is a row to insert
        :param commit: Whether to commit the changes to the database
        :return:
        """
        self.run_many(f"INSERT INTO {table_name} ({', '.join(columns[0].keys())}) VALUES ({', '.join(['?' for _ in columns[0]])})",
                      tuple(columns), commit=commit)

    def update(self, table_name, columns: dict, where: dict, commit=True):
        """
        Updates a row in a table
        :param table_name: The name of the table to update
        :param columns: A dictionary of column names and values to update
        :param where: A dictionary of column names and values to filter by
        :param commit: Whether to commit the changes to the database
        :return:
        """
        self.run(f"UPDATE {table_name} SET {', '.join([f'{column} = ?' for column in columns])} WHERE "
                 f"{', '.join([f'{column} = ?' for column in where])}",
                 tuple(columns.values()) + tuple(where.values()), commit=commit)


def get_local_ip():
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    raise NotImplementedError


class RoomController:

    def __init__(self, db_path: str = "room_data.db"):
        self.database = ConcurrentDatabase(db_path, check_same_thread=False)
        self.init_database()

        self.magic_home = MagicHueAPI.MagicHome(database=self.database)
        self.vesync = VeSyncAPI.VeSyncAPI(database=self.database)
        self.monkey = VoiceMonkeyAPI.VoiceMonkeyAPI(database=self.database)
        self.occupancy_detector = OccupancyDetector.OccupancyDetector(self.database)

        self.controllers = [self.magic_home, self.vesync, self.monkey]

        # with open("Modules/RoomControl/Configs/bluetooth_targets.json", "r") as f:
        #     bluetooth_targets = json.load(f)
        #     for mac, target in bluetooth_targets.items():
        #         self.blue_stalker.add_target(mac, target["name"], target["role"])
        #
        #     self.database.commit()

        # Wait for the other room controllers to be ready
        for controller in self.controllers:
            controller.wait_for_ready()

        self.sensor_host = SensorHost()

        self.environment_host = EnvironmentControllerHost(
            self.database,
            sensor_host=self.sensor_host,
            room_controllers=self.controllers
        )

        self.light_controller_host = LightControllerHost(
            self.database,
            self.occupancy_detector,
            room_controllers=self.controllers
        )

        self.controllers.append(self.environment_host)
        self.controllers.append(self.light_controller_host)
        self.controllers.append(self.occupancy_detector)

        self.scene_controller = SceneController(self.database, self.controllers)
        self.command_controller = CommandController(self.controllers)

        # Check what the operating system is to determine if we should run in dev mode
        self.webserver_port = 47670
        self.webserver_address = check_interface_usage(self.webserver_port)

        self.data_logging = DataLoggingHost(self.database,
                                            room_sensor_host=self.sensor_host, room_controllers=self.controllers)

        self.background()
        self.web_server = NetAPI(self.database,
                                 device_controllers=self.controllers,
                                 occupancy_detector=self.occupancy_detector,
                                 scene_controller=self.scene_controller,
                                 command_controller=self.command_controller,
                                 webserver_address=self.webserver_address,
                                 datalogger=self.data_logging)

    def init_database(self):
        cursor = self.database.cursor()
        cursor.execute('''CREATE TABLE IF NOT EXISTS auto_lights (device_id TEXT, is_auto BOOLEAN, current_mode TEXT)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS auto_plugs (device_id TEXT, is_auto BOOLEAN, policy_name TEXT)''')
        # cursor.execute('''CREATE TABLE IF NOT EXISTS scenes (scene_name TEXT, scene_data TEXT)''')

        cursor.execute('''CREATE TABLE IF NOT EXISTS secrets (secret_name TEXT, secret_value TEXT)''')
        self.database.commit()

    def refresh(self):
        # logging.info("Refreshing devices")

        for controller in self.controllers:
            if hasattr(controller, "refresh_all"):
                controller.refresh_all()

    @background
    def background(self):
        while True:
            for device in self.monkey.get_all_devices():
                device.main_power_state(self.vesync.get_device("plug_1").on)
            time.sleep(15)
