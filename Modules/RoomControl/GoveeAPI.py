import asyncio
import logging

import aiohttp

from Modules.RoomControl.AbstractSmartDevices import AbstractToggleDevice, background

logging.getLogger(__name__)


class GoveeAPI:

    def __init__(self, database):
        self.database = database

        cursor = self.database.cursor()
        self.api_key = cursor.execute("SELECT * FROM secrets WHERE secret_name = 'VoiceMonkeyKey'").fetchone()[1]
        self.api_secret = cursor.execute("SELECT * FROM secrets WHERE secret_name = 'VoiceMonkeySecret'").fetchone()[1]
        cursor.close()

    def init_database(self):
        cursor = self.database.cursor()
        cursor.execute("CREATE TABLE IF NOT EXISTS "
                       "voicemonkey_devices (device_name TEXT, on_monkey TEXT, off_monkey TEXT, current_state BOOLEAN)")
        cursor.close()
        self.database.commit()

    def get_device(self, device_name):
        return None

    def get_all_devices(self):
        return []


class VoiceMonkeyDevice(AbstractToggleDevice):

    def __init__(self, device_id, database):
        self.name = device_id
        self.database = database
        self.cached_details = {}

    def name(self):
        return self.name

    @background
    def set_on(self, on: bool):
        logging.debug(f"Setting {self.name} to {on}")

    @background
    def refresh_info(self):
        logging.debug(f"Refreshing {self.name} info")

    def get_status(self):
        return False
