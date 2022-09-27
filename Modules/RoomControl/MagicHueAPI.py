import logging

import magichue
import asyncio
from threading import Thread

from Modules.RoomControl.AbstractSmartDevices import AbstractRGB, background

logging = logging.getLogger(__name__)


def bulb_type_to_string(bulb_type: magichue.light.bulb_types):
    match bulb_type:
        case 51:
            return "RGB"
        case 6:
            return "RGBW"
        case _:
            return "Unknown"


class bulb_types:
    RGB = 6
    RGBW = 51


class MagicHome:

    def __init__(self, database):
        self.database = database

        cursor = self.database.cursor()
        username = cursor.execute("SELECT * FROM secrets WHERE secret_name = 'MagicHueUsername'").fetchone()[1]
        password = cursor.execute("SELECT * FROM secrets WHERE secret_name = 'MagicHuePassword'").fetchone()[1]
        cursor.close()

        self.api = magichue.RemoteAPI.login_with_user_password(user=username, password=password)
        self.devices = []
        self.ready = False
        self.fetch_all_devices()

        # self.state_changed = asyncio.Event()

    def wait_for_ready(self):
        while not self.ready:
            pass

    @background
    def fetch_all_devices(self):
        # Make a future to get all devices as the api call is blocking
        hw_devices = self.api.get_all_devices()
        # Wait for the future to complete
        devices = []
        for device in hw_devices:
            try:
                logging.info(f"MagicHome: Found device {device.macaddr}, creating device object")
                devices.append(MagicDevice(self.api, device.macaddr, database=self.database))
            except magichue.exceptions.MagicHueAPIError as e:
                logging.error(f"MagicHome: Error creating device object for {device.macaddr}: {e}")
        self.devices = devices
        self.ready = True

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
                    device.set_color((15, 0, 0))
                else:
                    device.set_color((255, 255, 255))
                    device.set_white(True)
                    device.set_brightness(255)

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
            device.fetch_status()


class MagicDevice(AbstractRGB):

    def __init__(self, api, macaddr, database=None):
        super().__init__(macaddr, database=database)
        self.online = False
        self.api = api

        if database is not None:
            cursor = database.cursor()
            self.is_auto = True if cursor.execute("SELECT * FROM auto_lights WHERE device_id = ?", (macaddr,)).fetchone()[1] == 1 else False
            self.auto_mode = cursor.execute("SELECT * FROM auto_lights WHERE device_id = ?", (macaddr,)).fetchone()[2]
            cursor.close()

        try:
            self.light = magichue.RemoteLight(api=api, macaddr=macaddr, allow_fading=True)
            logging.info(f"MagicHomeDevice: {macaddr} is ready, bulb type is "
                         f"{bulb_type_to_string(self.light.status.bulb_type)}")
            self.status = self.light.status
            self.bulb_type = self.light.status.bulb_type
        except magichue.exceptions.MagicHueAPIError as e:
            logging.error(f"MagicHomeDevice: Error creating device object for {macaddr}: {e}")
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
                # if self.bulb_type == bulb_types.RGBW and False:
                #     r, g, b = color
                #     if r == g == b and False:
                #         self.light.is_white = True
                #         self.light.w = r
                #     else:
                #         self.light.is_white = False
                #         self.light.rgb = color
                # else:
                self.light.is_white = False
                self.light.rgb = color
            except magichue.exceptions.MagicHueAPIError as e:
                print(f"{self.macaddr} set color error: {e}")
                self.offline_reason = str(e)
                self.online = False

    @background
    def set_brightness(self, brightness: int):
        if self.online:
            try:
                self.light.brightness = brightness
            except magichue.exceptions.MagicHueAPIError as e:
                print(f"{self.macaddr} set brightness error: {e}")
                self.online = False
                self.offline_reason = str(e)
        else:
            print(f"{self.macaddr} is offline")

    @background
    def set_on(self, on: bool):
        if self.online:
            try:
                self.light.on = on
            except magichue.exceptions.MagicHueAPIError as e:
                print(f"{self.macaddr} set brightness error: {e}")
                self.online = False
                self.offline_reason = str(e)
        else:
            print(f"{self.macaddr} is offline")

    @background
    def set_white(self, white: int):
        if self.online:
            try:
                if not self.light.on:
                    self.light.on = True
                # Check if the light supports warm white
                if self.bulb_type == bulb_types.RGBW:
                    self.light.is_white = True
                    self.light.w = white
                else:
                    self.light.color = (white, white, white)
                # self.light.cw = white
            except magichue.exceptions.MagicHueAPIError as e:
                print(f"{self.macaddr} set brightness error: {e}")
                self.offline_reason = str(e)
                self.online = False
        else:
            print(f"{self.macaddr} is offline")

    def is_white(self):
        if self.online:
            return self.light.is_white
        else:
            return False

    @background
    def toggle(self):
        if self.online:
            try:
                self.light.on = not self.light.on
            except magichue.exceptions.MagicHueAPIError as e:
                print(f"{self.macaddr} toggle error: {e}")
                self.offline_reason = str(e)
                self.online = False
        else:
            print(f"{self.macaddr} is offline")

    def get_color(self):
        if self.online:
            return self.light.rgb
        else:
            return 0, 0, 0

    def get_brightness(self):
        if self.online:
            return self.light.brightness
        else:
            return 0

    def get_hsv(self) -> tuple:
        if self.online:
            # Convert RGB to HSV
            r, g, b = self.light.rgb
            r, g, b = r / 255.0, g / 255.0, b / 255.0
            mx = max(r, g, b)
            mn = min(r, g, b)
            df = mx - mn
            if mx == mn:
                h = 0
            elif mx == r:
                h = (60 * ((g - b) / df) + 360) % 360
            elif mx == g:
                h = (60 * ((b - r) / df) + 120) % 360
            elif mx == b:
                h = (60 * ((r - g) / df) + 240) % 360
            else:
                h = 0
            if mx == 0:
                s = 0
            else:
                s = df / mx
            v = mx
            return h, s, v  # h: 0-360, s: 0-1, v: 0-1
        else:
            return 0, 0, 0

    def is_on(self):
        if self.online:
            return self.light.on
        else:
            return False

    def get_status(self):
        if self.online:
            try:
                status = {
                    "on": self.light.on,
                    "brightness": self.light.brightness,
                    "color": self.light.rgb,
                    "white": self.light.w,
                    "cold_white": self.light.cw,
                    "white_enabled": self.light.is_white,
                    "mode": self.light.mode._status_text() if not self.is_auto else "AUTOMATIC",
                }
                return status
            except magichue.exceptions.MagicHueAPIError as e:
                print(f"{self.macaddr} get status error: {e}")
                self.offline_reason = str(e)
                self.online = False
        return None

    @background
    def fetch_status(self):
        if self.online:
            try:
                self.light.update_status()
            except magichue.exceptions.MagicHueAPIError as e:
                print(f"{self.macaddr} get status error: {e}")
                self.offline_reason = str(e)
                self.online = False
        else:
            # Attempt to reconnect
            try:
                self.light = magichue.RemoteLight(api=self.api, macaddr=self.macaddr)
                self.online = True
            except magichue.exceptions.MagicHueAPIError as e:
                # print(f"{self.macaddr} reconnect error: {e}")
                self.offline_reason = str(e)
                self.online = False

    def is_online(self):
        return self.online
