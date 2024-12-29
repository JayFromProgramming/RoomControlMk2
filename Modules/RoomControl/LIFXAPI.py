import time

import pifx
from lifxlan import LifxLAN, Light
from Modules.RoomControl.AbstractSmartDevices import AbstractRGB
from Modules.RoomControl.Decorators import background
from Modules.RoomModule import RoomModule
from Modules.RoomObject import RoomObject
from loguru import logger as logging


class LIFXAPI(RoomModule):

    def __init__(self, room_controller):
        super().__init__(room_controller)
        self.database = room_controller.database
        self.name = "LIFXAPI"
        logging.info("Starting LIFXAPI, searching for devices")
        self.room_controller = room_controller
        self.database = room_controller.database
        # secrets = self.database.get_table("secrets")
        # self.lifx = pifx.PIFX(secrets.get_row(secret_name="lifx_key")["secret_value"])
        # print(self.lifx.list_lights())
        self.lifx = LifxLAN()
        self.room_objects = []
        self.periodic_device_scan()

    @background
    def periodic_device_scan(self):
        while True:
            self.lifx.discover_devices()
            api_devices = self.lifx.get_lights()
            for device in api_devices:
                if not [x for x in self.room_objects if x.object_name == device.get_mac_addr()]:
                    self.room_objects.append(LIFXDevice(device, self.room_controller))
                    logging.info(f"Found new LIFX device {device.get_label()}")
            time.sleep(60)


class LIFXDevice(RoomObject, AbstractRGB):
    is_promise = False
    supported_actions = ["on", "brightness", "fade", "white"]

    def __init__(self, device, room_controller):
        super().__init__(device.get_mac_addr(), "LIFXDevice")
        logging.info(f"Creating LIFXDevice {device.get_label()}: {device.get_mac_addr()}@{device.get_ip_addr()}")
        self.device = device
        self.current_power = 0
        self.current_color = None

        self.info_refresh()
        room_controller.attach_object(self)

    def name(self):
        return self.object_name

    def set_color(self, color: tuple):
        self.device.set_color(color)

    def get_color(self) -> list:
        return self.device.get_color()

    def set_brightness(self, brightness: int):
        self.set_white(brightness)

    def get_brightness(self) -> int:
        return self.get_white()

    def _brightness_to_byte(self, brightness: int):
        """
        Convert the 0-65535 brightness to 0-255
        :param brightness: The brightness to convert
        :return:
        """
        return int(brightness / 65535 * 255)

    def _brightness_to_lifx(self, brightness: int):
        """
        Convert the 0-255 brightness to 0-65535
        :param brightness: The brightness to convert
        :return:
        """
        return int(brightness / 255 * 65535)

    def _hsbk_to_rgbw(self, hsbk: list):
        """
        Convert HSBK to RGBW
        :param hsbk: The HSBK to convert
        :return:
        """
        pass

    def _rgbw_to_hsbk(self, rgbw: list):
        """
        Convert RGBW to HSBK
        :param rgbw: The RGBW to convert
        :return:
        """
        pass

    def get_status(self):
        return {
            "on": self.current_power > 0,
            "brightness": self.get_brightness(),
            "color": self.current_color,
            "cold_white": 0,
            "warm_white": self.get_white(),
            "white_enabled": True,
            "mode": "NORMAL" if not self.fading else "FADING",
            "control_type": "AUTO-FADE" if not self.fading else "MANUAL"
        }

    def get_info(self) -> dict:
        try:
            return {
                "ip": self.device.get_ip_addr(),
                "firmware": self.device.get_host_firmware_version(),
                "wifi": self.device.get_wifi_info_tuple(),
                "misc": self.device.get_info_tuple()
            }
        except Exception:
            return {
                "ip": "Unknown",
                "firmware": "Unknown",
                "wifi": "Unknown",
                "misc": "Unknown"
            }

    def set_on(self, on: bool):
        self.device.set_power(on)

    def get_on(self) -> bool:
        return self.device.get_power() > 0

    def set_white(self, white: int):
        if white > 0 and not self.get_on():
            self.set_on(True)
        self.device.set_color([0, 0, self._brightness_to_lifx(white), self.current_color[3]])

    def get_white(self):
        return self._brightness_to_byte(self.current_color[2])

    @background
    def info_refresh(self):
        while True:
            self.online = True
            try:
                self.device.get_time()
                self.current_power = self.device.get_power()
                self.current_color = self.device.get_color()
            except Exception as e:
                self.online = False
                self.offline_reason = "No Device Response"
                logging.error(f"Error refreshing LIFX device {self.device.get_label()}: {e}")
            time.sleep(5)
