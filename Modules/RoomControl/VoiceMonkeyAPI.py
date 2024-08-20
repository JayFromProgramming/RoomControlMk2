import asyncio
import random
import time

import aiohttp
import requests

import ConcurrentDatabase
from Modules.RoomControl.AbstractSmartDevices import AbstractToggleDevice

from Modules.RoomControl.Decorators import background

from loguru import logger as logging

from Modules.RoomModule import RoomModule
from Modules.RoomObject import RoomObject

template = "https://api.voicemonkey.io/trigger?access_token={token}&secret_token={secret}&monkey={monkey}"


class VoiceMonkeyAPI(RoomModule):

    def __init__(self, room_controller):
        super().__init__(room_controller)
        self.room_controller = room_controller
        self.database = room_controller.database
        self.init_database()

        secrets = self.database.get_table("secrets")
        self.api_key = secrets.get_row(secret_name='VoiceMonkeyKey')['secret_value']
        self.api_secret = secrets.get_row(secret_name='VoiceMonkeySecret')['secret_value']

        self.devices = []
        cursor = self.database.cursor()
        for device in cursor.execute("SELECT * FROM voicemonkey_devices").fetchall():
            self.devices.append(
                VoiceMonkeyDevice(device[0], self.room_controller, self.api_key, self.api_secret, device[4]))

        self.periodic_refresh()

    def wait_for_ready(self):
        pass

    def init_database(self):
        self.database.create_table("voicemonkey_devices", {"device_name": "TEXT", "on_monkey": "TEXT",
                                                           "off_monkey": "TEXT", "current_state": "BOOLEAN"})
        self.database.update_table("voicemonkey_devices", 1,
                                   ["""ALTER TABLE voicemonkey_devices ADD COLUMN govee_host TEXT"""])

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


class VoiceMonkeyDevice(RoomObject, AbstractToggleDevice):
    """All voice monkey devices store their state in the database, so we don't need to query the device for its state"""

    is_promise = False  # Indicates to whatever references this object that it is now ready to be used
    supported_actions = ["toggleable"]

    def __init__(self, device_id, room_controller, monkey_token, monkey_secret, govee_host=None):
        super().__init__(device_id, "VoiceMonkeyDevice")
        self.device_id = device_id
        self.room_controller = room_controller
        self.govee_host = govee_host
        self.database = room_controller.database
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
        self.auto = False
        self.room_controller.attach_object(self)

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

    @property
    def white(self):
        return 255 if self.current_state else 0

    @white.setter
    def white(self, value):
        if value:
            self.set_on(True)
        else:
            self.set_on(False)

    @property
    def on(self):
        return self.current_state

    @on.setter
    def on(self, value):
        self.set_on(value)

    def set_on(self, on: bool):
        if on:
            self.run_monkey(self.enable_monkey, True)
        else:
            self.run_monkey(self.disable_monkey, False)

    @background
    def run_monkey(self, monkey, state_after=None):

        device_host = self.room_controller.get_module("GoveeAPI").get_device(self.govee_host)
        if device_host is None:
            # logging.error(f"VoiceMonkey ({monkey}): Could not find Govee device {self.govee_host}")
            self.online = False
            self.offline_reason = "Govee Device Not Found"
            return
        else:
            self.online = device_host.online if device_host.initialized else True
            self.offline_reason = "Plug Offline" if not device_host.online else "Unknown"
            if not device_host.online:
                return

        url = template.format(token=self.monkey_token, secret=self.monkey_secret, monkey=monkey)
        logging.debug(f"Running monkey {monkey}")
        try:
            resp = requests.get(url)
        except requests.exceptions.ConnectionError as e:
            try:
                cause = e.args[0].reason
                self.fault = True
                self.offline_reason = f"{type(cause).__name__}"
                # Get the cause of the connection error
                logging.error(f"VoiceMonkey ({monkey}): Could not connect to VoiceMonkey server ({cause})")
            except Exception:
                logging.error(f"VoiceMonkey ({monkey}): Could not connect to VoiceMonkey server, unknown error")
                self.fault = True
                self.offline_reason = "UnknownConnError"
        except Exception as e:
            logging.error(f"VoiceMonkey ({monkey}): Unknown error ({e})")
            self.online = True
            self.offline_reason = "Request Error"
        else:
            if resp.status_code == 200:
                logging.debug(f"Monkey {monkey} queued successfully")
                self.fault = False
                if device_host is not None and device_host.online:
                    self.offline_reason = "Unknown"
                if state_after is not None:
                    self.current_state = state_after
                    self.row.set(current_state=state_after)
            else:
                logging.error(f"Monkey {monkey} failed to queue, status code {resp.status_code}\n{resp.text}")
                self.fault = True
                self.offline_reason = f"API Error, code: {resp.status_code}"

    def refresh_info(self):
        logging.debug(f"Refreshing {self.name} info")

    def get_status(self):
        return True if self.current_state == 1 else False

    def refresh_state(self):
        self.run_monkey(self.enable_monkey if self.current_state else self.disable_monkey)

    def __str__(self):
        return f"VoiceMonkeyDevice: {self.device_id} - {self.current_state}"