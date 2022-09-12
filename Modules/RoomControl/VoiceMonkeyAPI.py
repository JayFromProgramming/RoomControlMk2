import asyncio
import logging
import random
import time

import aiohttp
import requests

from Modules.RoomControl.AbstractSmartDevices import AbstractToggleDevice, background

logging = logging.getLogger(__name__)

template = "https://api.voicemonkey.io/trigger?access_token={token}&secret_token={secret}&monkey={monkey}"


class VoiceMonkeyAPI:

    def __init__(self, database):
        self.database = database
        self.init_database()

        cursor = self.database.cursor()
        self.api_key = cursor.execute("SELECT * FROM secrets WHERE secret_name = 'VoiceMonkeyKey'").fetchone()[1]
        self.api_secret = cursor.execute("SELECT * FROM secrets WHERE secret_name = 'VoiceMonkeySecret'").fetchone()[1]
        cursor.close()

        self.devices = []
        cursor = self.database.cursor()
        for device in cursor.execute("SELECT * FROM voicemonkey_devices").fetchall():
            self.devices.append(
                VoiceMonkeyDevice(device[0], self.database, self.api_key, self.api_secret))

        self.periodic_refresh()

    def init_database(self):
        cursor = self.database.cursor()
        cursor.execute("CREATE TABLE IF NOT EXISTS "
                       "voicemonkey_devices (device_name TEXT, on_monkey TEXT, off_monkey TEXT, current_state BOOLEAN)")
        cursor.close()
        self.database.commit()

    def get_device(self, device_name):
        for device in self.devices:
            if device.device_id == device_name:
                return device

    def get_all_devices(self):
        return self.devices

    @background
    def periodic_refresh(self):
        """Periodically sends a command that matches the current state of
         the device so that if the device either missed its last command or
         was turned on/off manually, it will update to the correct state"""
        logging.info("Starting VoiceMonkey periodic refresh")
        while True:
            for device in self.devices:
                time.sleep(random.randint(15, 40))
                device.refresh_state()
                logging.debug(f"Refreshed VoiceMonkey device {device.device_id}")



class VoiceMonkeyDevice(AbstractToggleDevice):
    """All voice monkey devices store their state in the database, so we don't need to query the device for its state"""

    def __init__(self, device_id, database, monkey_token, monkey_secret):
        super().__init__()
        self.device_id = device_id
        self.database = database
        self.monkey_token = monkey_token
        self.monkey_secret = monkey_secret
        self.enable_monkey = None
        self.disable_monkey = None
        self.current_state = None
        self.load_state()
        self.online = True

    def load_state(self):
        cursor = self.database.cursor()
        cursor.execute("SELECT * FROM voicemonkey_devices WHERE device_name = ?", (self.device_id,))
        row = cursor.fetchone()
        if row:
            self.enable_monkey = row[1]
            self.disable_monkey = row[2]
            self.current_state = row[3]
            self.set_on(self.current_state)
        else:
            logging.error(f"Could not find {self.name} in database")

        cursor.close()

    def get_type(self):
        return "VoiceMonkeyDevice"

    def name(self):
        return self.device_id

    def is_on(self):
        return self.current_state

    def set_on(self, on: bool):
        if on:
            self.run_monkey(self.enable_monkey, True)
        else:
            self.run_monkey(self.disable_monkey, False)

    @background
    def run_monkey(self, monkey, state_after=None):
        url = template.format(token=self.monkey_token, secret=self.monkey_secret, monkey=monkey)
        logging.info(f"Running monkey {monkey}")
        resp = requests.get(url)
        if resp.status_code == 200:
            logging.info(f"Monkey {monkey} ran successfully")
            if state_after is not None:
                self.current_state = state_after
                cursor = self.database.cursor()
                cursor.execute("UPDATE voicemonkey_devices SET current_state = ? WHERE device_name = ?",
                               (state_after, self.device_id))
                cursor.close()
                self.database.lock.acquire()
                self.database.commit()
                self.database.lock.release()
        else:
            logging.error(f"Monkey {monkey} failed to run, status code {resp.status_code}")

    def refresh_info(self):
        logging.debug(f"Refreshing {self.name} info")

    def get_status(self):
        return True if self.current_state == 1 else False

    def refresh_state(self):
        self.run_monkey(self.enable_monkey if self.current_state else self.disable_monkey)
