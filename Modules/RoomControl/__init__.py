import json
import logging
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

logging.getLogger(__name__)


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
        cursor = super().cursor()
        self.lock.acquire()
        cursor.execute(sql, *args)
        self.lock.release()
        if kwargs.get("commit", True):
            super().commit()
        return cursor

    def get(self, sql, *args):
        cursor = self.run(sql, *args)
        result = cursor.fetchall()
        cursor.close()
        return result


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
        if os.name == "nt":  # Windows
            address = "localhost"
            logging.info("Running in dev mode, using localhost")
        else:  # Anything else
            address = "wopr.eggs.loafclan.org"
            logging.info("Running in prod mode, using wopr.eggs.loafclan.org")

        self.data_logging = DataLoggingHost(self.database,
                                            room_sensor_host=self.sensor_host, room_controllers=self.controllers)

        self.background()
        self.web_server = NetAPI(self.database,
                                 device_controllers=self.controllers,
                                 occupancy_detector=self.occupancy_detector,
                                 scene_controller=self.scene_controller,
                                 command_controller=self.command_controller,
                                 webserver_address=address,
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
