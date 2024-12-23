from lifxlan import LifxLAN
from Modules.RoomControl.AbstractSmartDevices import AbstractRGB
from Modules.RoomControl.Decorators import background
from Modules.RoomModule import RoomModule
from Modules.RoomObject import RoomObject
from loguru import logger as logging


class LIFXAPI(RoomModule):

    def __init__(self, room_controller):
        super().__init__(room_controller)
        self.name = "LIFXAPI"
        logging.info("Starting LIFXAPI, searching for devices")
        self.room_controller = room_controller
        self.database = room_controller.database
        self.lifx = LifxLAN()
        self.api_devices = self.lifx.get_lights()
        self.room_objects = []
        for device in self.api_devices:
            if device.supports_color() or device.supports_temperature():
                self.room_objects.append(LIFXDevice(device, room_controller))
        logging.info(f"Found {len(self.room_objects)} LIFX devices")


class LIFXDevice(RoomObject, AbstractRGB):

    def __init__(self, device, room_controller):
        super().__init__(device.get_mac_addr(), "LIFXDevice")
        logging.info(f"Creating LIFXDevice {device.get_label()}: {device.get_mac_addr()}@{device.get_ip_addr()}")
        self.device = device

        room_controller.attach_object(self)

    def name(self):
        return self.object_name

    def set_color(self, color: tuple):
        self.device.set_color(color)

    def get_color(self) -> list:
        return self.device.get_color()

    def set_brightness(self, brightness: int):
        self.device.set_brightness(brightness)


