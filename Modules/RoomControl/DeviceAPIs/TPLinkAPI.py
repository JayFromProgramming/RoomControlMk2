import asyncio
from kasa import Discover, Device

from Modules.RoomControl.AbstractSmartDevices import AbstractRGB
from Modules.RoomControl.Decorators import background
from Modules.RoomModule import RoomModule
from Modules.RoomObject import RoomObject
from loguru import logger as logging


class TPLinkAPI(RoomModule):
    requires_async = True

    def __init__(self, room_controller):
        super().__init__(room_controller)
        self.room_controller = room_controller
        self.devices = []

    async def start(self):
        logging.info("Starting TPLinkAPI event loop")
        await self.discover_devices()
        await self.start_device_command_queue_handlers()
        await self.refresh_device_data()

    async def discover_devices(self):
        logging.info("Starting TPLinkAPI, starting device scan")
        try:
            # TODO: Remove hardcoded IP and implement a proper device discovery
            device = await Device.connect(host="192.168.1.18")
            self.devices.append(TPLinkDevice(device, self.room_controller))
        except Exception as e:
            logging.error(f"Error scanning for TPLink devices: {e}")
            logging.exception(e)

    async def start_device_command_queue_handlers(self):
        """
        Starts an asyncio task for each device to listen for commands in the device_command_queue
        :return:
        """
        for device in self.devices:
            asyncio.create_task(device.send_commands())

    async def refresh_device_data(self):
        while True:
            for device in self.devices:
                try:
                    await device.refresh_info()
                except Exception as e:
                    logging.error(f"Error refreshing TPLink device {device.device_name}: {e}")
                    logging.exception(e)
                finally:
                    await asyncio.sleep(1)


class TPLinkDevice(RoomObject, AbstractRGB):

    is_promise = False
    supported_actions = ["on", "brightness", "fade", "white"]

    def __init__(self, device, room_controller):
        super().__init__(device.mac, "TPLinkDevice")
        self.device = device
        self.device_name = device.alias
        self.device_id = device.mac
        self.device_type = "TPLinkDevice"
        logging.info(f"Creating TPLinkDevice {self.device_name}: {self.device_id}@{self.device.host}")

        self.device_command_queue = asyncio.Queue()
        self.device_state_cache = {}

        self.last_brightness_command = -1

        room_controller.attach_object(self)

    async def refresh_info(self):
        try:
            await self.device.update()
        except Exception as e:
            logging.error(f"Error refreshing TPLink device {self.device_name}: {e}")
            # logging.exception(e)
            self.device_state_cache = {
                "on": False,
                "brightness": 0,
                "color": [0, 0, 0],
                "white": 0,
                "rssi": 0,
                "online": False,
                "reason": str(e)
            }
            return
        on = self.device.is_on
        brightness = self.device.brightness / 100 * 255
        # Because the kasa brightness is 0-100 and the RoomControl brightness is 0-255,
        # we scale the brightness to 0-255 and then look for the last brightness command
        # so we can return the exact commanded brightness if the device is still within the range
        if self.last_brightness_command != -1:
            # Check if the current brightness is within 5 of the last commanded brightness
            if abs(brightness - self.last_brightness_command) < 5:
                brightness = self.last_brightness_command
            else:
                self.last_brightness_command = -1
        rssi = self.device.rssi
        self.device_state_cache = {
            "on": on,
            "brightness": brightness,
            "color": [0, 0, 0],
            "white": brightness,
            "rssi": rssi,
            "online": True,
        }

    async def send_commands(self):
        logging.info(f"Starting command queue handler for TPLink device {self.device_name}")
        while True:
            try:
                command = await self.device_command_queue.get()
                match command[0]:
                    case "set_color":
                        await self.device.set_color(command[1])
                    case "set_brightness":
                        await self.device.set_brightness(command[1])
                        self.last_brightness_command = command[1]
                    case "set_white":
                        await self.device.set_brightness(command[1])
                        self.last_brightness_command = command[1]
                    case "set_on":
                        await self.device.set_state(command[1])
            except Exception as e:
                logging.error(f"Error sending command to TPLink device {self.device_name}: {e}")
                # logging.exception(e)

    def name(self):
        return self.device_id

    def get_type(self):
        return self.device_type

    def set_color(self, color: list):
        self.device_command_queue.put_nowait(("set_color", color))

    def get_color(self) -> list:
        return self.device_state_cache.get("color", [0, 0, 0])

    def set_brightness(self, brightness: int):
        self.device_command_queue.put_nowait(("set_brightness", round(brightness / 255 * 100)))

    def get_brightness(self) -> int:
        return self.device_state_cache.get("brightness", 0)

    def set_white(self, white: int):
        self.set_brightness(white)

    def get_white(self) -> int:
        return self.device_state_cache.get("white", 0)

    def set_on(self, on: bool):
        self.device_command_queue.put_nowait(("set_on", on))

    def get_on(self) -> bool:
        return self.device_state_cache.get("on", None)

    def get_status(self):
        return {
            "on": self.device_state_cache.get("on", False),
            "brightness": self.device_state_cache.get("brightness", 0),
            "color": self.device_state_cache.get("color", [0, 0, 0]),
            "cold_white": 0,
            "warm_white": self.device_state_cache.get("white", 0),
            "white_enabled": False,
            "fade_active": False,
        }

    def get_health(self) -> dict:
        return {
            "online": self.device_state_cache.get("online", False),
            "reason": self.device_state_cache.get("reason", "Unknown")
        }

    def get_info(self) -> dict:
        return {
            "rssi": self.device_state_cache.get("rssi", 0),
        }



