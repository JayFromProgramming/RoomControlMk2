import logging

import magichue
import asyncio
from threading import Thread

from Modules.RoomControl.AbstractSmartDevices import AbstractRGB, background

logging.getLogger(__name__)


class MagicHome:

    def __init__(self, database):
        self.database = database

        cursor = self.database.cursor()
        username = cursor.execute("SELECT * FROM secrets WHERE secret_name = 'MagicHueUsername'").fetchone()[1]
        password = cursor.execute("SELECT * FROM secrets WHERE secret_name = 'MagicHuePassword'").fetchone()[1]
        cursor.close()

        self.api = magichue.RemoteAPI.login_with_user_password(user=username, password=password)
        self.devices = asyncio.run(self.fetch_all_devices())

        self.state_changed = asyncio.Event()

    async def fetch_all_devices(self):
        # Make a future to get all devices as the api call is blocking
        future = asyncio.get_event_loop().run_in_executor(None, self.api.get_all_devices)
        # Wait for the future to complete
        hw_devices = await future
        devices = []
        for device in hw_devices:
            try:
                print(f"Adding device: {device.macaddr}")
                devices.append(MagicDevice(self.api, device.macaddr, database=self.database))
            except magichue.exceptions.MagicHueAPIError as e:
                logging.error(f"\t{device.macaddr}: Error: {e}")
        return devices

    def get_device(self, macaddr):
        for device in self.devices:
            if device.macaddr == macaddr:
                return device
        return None

    def get_all_devices(self):
        return self.devices

    def online_device_count(self):
        count = 0
        for device in self.devices:
            if device.online:
                count += 1
        return count

    def auto_on(self, on: bool):
        for device in self.devices:
            if device.is_auto:
                if not on:
                    device.set_color((1, 0, 0))
                else:
                    device.set_color((255, 255, 255))
                    device.set_white(True)

    def total_devices(self):
        return len(self.devices)

    def set_all_color(self, color: tuple):
        for device in self.devices:
            device.set_color(color)

    def set_all_brightness(self, brightness: int):
        for device in self.devices:
            device.set_brightness(brightness)

    def set_all_on(self, on: bool):
        for device in self.devices:
            device.set_on(on)

    def set_all_white(self, white: int):
        for device in self.devices:
            device.set_white(white)

    def get_all_status(self):
        all_status = {}
        for device in self.devices:
            all_status[device.macaddr] = device.get_status()
        return all_status

    def refresh_all(self):
        for device in self.devices:
            device.refresh_info()


class MagicDevice(AbstractRGB):

    def __init__(self, api, macaddr, database=None):
        super().__init__(macaddr, database=database)
        self.online = False

        if database is not None:
            cursor = database.cursor()
            self.is_auto = True if cursor.execute("SELECT * FROM auto_lights WHERE device_id = ?", (macaddr,)).fetchone()[1] == 1 else False
            self.auto_mode = cursor.execute("SELECT * FROM auto_lights WHERE device_id = ?", (macaddr,)).fetchone()[2]
            cursor.close()

        try:
            self.light = magichue.RemoteLight(api=api, macaddr=macaddr)
            self.status = self.light.status
        except magichue.exceptions.MagicHueAPIError as e:
            logging.error(f"{macaddr} creation error: {e}")
            self.light = None
        else:
            self.online = True
        self.macaddr = macaddr
        self._background_thread = None  # type: None or Thread

    def __str__(self):
        if self.online:
            return f"[{self.macaddr}: On: {self.light.on}, Brightness: {self.light.brightness}, Color: {self.light.rgb}]"
        else:
            return f"{self.macaddr}: Offline"

    def __repr__(self):
        return self.__str__()

    def name(self):
        return self.macaddr

    @background
    def set_color(self, color: tuple):
        if self.online:
            try:
                self.light.is_white = False
                self.light.rgb = color
            except magichue.exceptions.MagicHueAPIError as e:
                print(f"{self.macaddr} set color error: {e}")
                self.online = False

    @background
    def set_brightness(self, brightness: int):
        if self.online:
            try:
                self.light.brightness = brightness
            except magichue.exceptions.MagicHueAPIError as e:
                print(f"{self.macaddr} set brightness error: {e}")
                self.online = False

    @background
    def set_on(self, on: bool):
        if self.online:
            try:
                self.light.on = on
            except magichue.exceptions.MagicHueAPIError as e:
                print(f"{self.macaddr} set brightness error: {e}")
                self.online = False

    @background
    def set_white(self, white: int):
        if self.online:
            try:
                self.light.is_white = True
                self.light.w = white
                self.light.cw = white
            except magichue.exceptions.MagicHueAPIError as e:
                print(f"{self.macaddr} set brightness error: {e}")
                self.online = False

    @background
    def toggle(self):
        if self.online:
            try:
                self.light.toggle()
            except magichue.exceptions.MagicHueAPIError as e:
                print(f"{self.macaddr} toggle error: {e}")
                self.online = False

    def is_on(self):
        if self.online:
            return self.light.on
        else:
            return False

    def get_status(self):
        if self.online:
            try:
                self.light.update_status()
                status = {
                    "on": self.light.on,
                    "brightness": self.light.brightness,
                    "color": self.light.rgb,
                    "white": self.light.w,
                    "cold_white": self.light.cw,
                    "white_enabled": self.light.is_white
                }
                return status
            except magichue.exceptions.MagicHueAPIError as e:
                print(f"{self.macaddr} get status error: {e}")
                self.online = False

    @background
    def refresh_info(self):
        if self.online:
            try:
                self.light.update_status()
            except magichue.exceptions.MagicHueAPIError as e:
                print(f"{self.macaddr} get status error: {e}")
                self.online = False
