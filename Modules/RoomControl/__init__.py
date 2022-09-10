import json
import logging
import sqlite3

from Modules.RoomControl import MagicHueAPI, VeSyncAPI, VoiceMonkeyAPI
from Modules.RoomControl.API.net_api import NetAPI
from Modules.RoomControl.OccupancyDetection.BluetoothOccupancy import BluetoothDetector

logging.getLogger(__name__)


class RoomController:

    def __init__(self, db_path: str = "room_data.db"):
        self.database = sqlite3.connect(db_path, check_same_thread=False)
        self.init_database()

        self.magic_home = MagicHueAPI.MagicHome(database=self.database)
        self.vesync = VeSyncAPI.VeSyncAPI(database=self.database)
        self.monkey = VoiceMonkeyAPI.VoiceMonkeyAPI(database=self.database)
        self.blue_stalker = BluetoothDetector(self.database)

        self.lights = self.magic_home.devices
        self.plugs = self.vesync.devices

        with open("Modules/RoomControl/Configs/bluetooth_targets.json", "r") as f:
            bluetooth_targets = json.load(f)
            for mac, target in bluetooth_targets.items():
                self.blue_stalker.add_target(mac, target["name"], target["role"])

            self.database.commit()

        self.web_server = NetAPI(self.database,
                                 device_controllers=[self.magic_home, self.vesync, self.monkey],
                                 occupancy_detector=self.blue_stalker)

    def init_database(self):
        cursor = self.database.cursor()
        cursor.execute('''CREATE TABLE IF NOT EXISTS auto_devices (device_id TEXT, is_auto BOOLEAN, current_mode TEXT, tier INTEGER)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS auto_modes (mode_name TEXT, is_active BOOLEAN, tier INTEGER)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS scenes (scene_name TEXT, scene_data TEXT)''')

        cursor.execute('''CREATE TABLE IF NOT EXISTS secrets (secret_name TEXT, secret_value TEXT)''')
        self.database.commit()

    def refresh(self):
        logging.info("Refreshing devices")
        self.magic_home.refresh_all()
        self.vesync.refresh()
