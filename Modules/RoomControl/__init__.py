import json
import socket
import sys

import netifaces as netifaces
from loguru import logger as logging
import sqlite3
import threading
import os
import time

from ConcurrentDatabase.Database import Database
from Modules.RoomControl import MagicHueAPI, VeSyncAPI, VoiceMonkeyAPI
from Modules.RoomControl.API.net_api import NetAPI
from Modules.RoomControl.Decorators import background
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
        except OSError as e:
            logging.warning(f"Interface {interface}:{port} was already in use: {e}")
            interfaces.remove(interface)
    return interfaces


def get_local_ip():
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    raise NotImplementedError


def database_backup(status, remaining, total):
    if remaining == 0:
        logging.info(f"Database backup complete, {total} pages backed up")
    else:
        logging.info(f"Database backup {status}, {remaining} pages remaining")


class RoomController:

    def __init__(self, db_path: str = "room_data.db"):
        self.database = Database(db_path)
        try:
            self.backup_database = sqlite3.connect(f"{db_path}.bak")
            self.database.backup(target=self.backup_database, progress=database_backup)
        except sqlite3.OperationalError:
            logging.warning("Backup database is already in use, skipping backup")
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
        if os.name == "posix":
            logging.info(f"Terminating all processes bound to port {self.webserver_port}")
            # Kill any processes that are using the port
            fuser_out = os.popen(f"fuser {self.webserver_port}/tcp").read()
            # Parse the output
            fuser_out = fuser_out.splitlines()
            logging.debug(fuser_out)
            for line in fuser_out:
                _, pid = line.split(":")
                # Remove all padding spaces
                pid = pid.strip()
                # Verify that we are not killing ourselves
                if int(pid) != os.getpid():
                    logging.info(f"Killing process {pid} to free up port {self.webserver_port}")
                    os.system(f"sudo kill {pid}")
                else:
                    logging.info(f"Skipping killing process {pid} as it is the current process")

        time.sleep(2.5)

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

    @background
    def background(self):
        while True:
            for device in self.monkey.get_all_devices():
                device.main_power_state(self.vesync.get_device("plug_1").on)
            time.sleep(15)
