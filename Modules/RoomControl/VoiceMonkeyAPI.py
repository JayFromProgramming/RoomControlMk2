import asyncio
import random
import time

import aiohttp
import requests

import ConcurrentDatabase
from Modules.RoomControl.AbstractSmartDevices import AbstractToggleDevice

from Modules.RoomControl.Decorators import background


from loguru import logger as logging

template = "https://api.voicemonkey.io/trigger?access_token={token}&secret_token={secret}&monkey={monkey}"


class VoiceMonkeyAPI:

    def __init__(self, database: ConcurrentDatabase.Database):
        self.database = database
        self.init_database()

        secrets = self.database.get_table("secrets")
        self.api_key = secrets.get_row(secret_name='VoiceMonkeyKey')['secret_value']
        self.api_secret = secrets.get_row(secret_name='VoiceMonkeySecret')['secret_value']

        self.devices = []
        cursor = self.database.cursor()
        for device in cursor.execute("SELECT * FROM voicemonkey_devices").fetchall():
            self.devices.append(
                VoiceMonkeyDevice(device[0], self.database, self.api_key, self.api_secret))

        self.periodic_refresh()

    def wait_for_ready(self):
        pass

    def init_database(self):
        self.database.create_table("voicemonkey_devices", {"device_name": "TEXT", "on_monkey": "TEXT",
                                                           "off_monkey": "TEXT", "current_state": "BOOLEAN"})

    def get_device(self, device_name):
        for device in self.devices:
            if device.device_id == device_name:
                return device

    def get_all_devices(self):
        return self.devices

    def refresh_all(self):
        pass
        # for device in self.devices:
        #     device.refresh_info()

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
                for device_2 in [device for device in self.devices if not device.online]:
                    device_2.refresh_state()
                    time.sleep(5)


class VoiceMonkeyDevice(AbstractToggleDevice):
    """All voice monkey devices store their state in the database, so we don't need to query the device for its state"""

    def __init__(self, device_id, database: ConcurrentDatabase.Database, monkey_token, monkey_secret):
        super().__init__()
        self.device_id = device_id
        self.database = database
        self.monkey_token = monkey_token
        self.monkey_secret = monkey_secret
        self.enable_monkey = None
        self.disable_monkey = None
        self.current_state = None
        self.online = True
        self.offline_reason = "Unknown"
        self.fault = False
        self.voice_monkey_table = self.database.get_table("voicemonkey_devices")
        self.row = self.voice_monkey_table.get_row(device_name=self.device_id)
        self.load_state()

    def main_power_state(self, state):
        if not state:
            self.fault = True
            self.offline_reason = "Power Outage"
        else:
            self.fault = False
            self.offline_reason = "Unknown"

    def load_state(self):
        if self.row:
            self.enable_monkey = self.row["on_monkey"]
            self.disable_monkey = self.row["off_monkey"]
            self.current_state = self.row["current_state"]
            self.set_on(self.current_state)
        else:
            logging.error(f"Could not find {self.name} in database")

    def get_type(self):
        return "VoiceMonkeyDevice"

    def name(self):
        return self.device_id

    def is_on(self):
        return self.get_status()

    def set_on(self, on: bool):
        if on:
            self.run_monkey(self.enable_monkey, True)
        else:
            self.run_monkey(self.disable_monkey, False)

    @background
    def run_monkey(self, monkey, state_after=None):
        url = template.format(token=self.monkey_token, secret=self.monkey_secret, monkey=monkey)
        logging.debug(f"Running monkey {monkey}")
        try:
            resp = requests.get(url)
        except requests.exceptions.ConnectionError as e:
            self.online = False
            self.offline_reason = "No API"
            logging.error(f"VoiceMonkey ({monkey}): Could not connect to VoiceMonkey server ({e})")
        else:
            if resp.status_code == 200:
                logging.debug(f"Monkey {monkey} queued successfully")
                if state_after is not None:
                    self.current_state = state_after
                    self.row.set(current_state=state_after)
                    self.online = True
                    # self.offline_reason = "Unknown"
            else:
                logging.error(f"Monkey {monkey} failed to queue, status code {resp.status_code}")
                self.online = False
                self.offline_reason = f"API Error, code: {resp.status_code}"

    def refresh_info(self):
        logging.debug(f"Refreshing {self.name} info")

    def get_status(self):
        return True if self.current_state == 1 else False

    def refresh_state(self):
        self.run_monkey(self.enable_monkey if self.current_state else self.disable_monkey)
