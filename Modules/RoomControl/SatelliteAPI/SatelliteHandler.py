import json
import asyncio
from typing import Optional
from loguru import logger as logging
from Modules.RoomControl.SatelliteAPI.SatelliteDevice import SatelliteDevice
from Modules.RoomObject import RoomObject
from Modules.RoomControl.SatelliteAPI.SatelliteLinkHandler import SatelliteLinkHandler


class SatelliteHandler:
    """
    Represents a satellite device in the room control system.
    This class is used to manage the satellite device's state and interactions.
    """

    def __init__(self, room_controller, connect_info):
        """
        Initialize the satellite device with the room controller and a unique device ID.

        :param room_controller: The room controller instance managing this device.
        :param device_id: A unique identifier for the satellite device.
        """
        satellite_id = connect_info.get("name", "unknown_satellite")
        self.room_controller = room_controller
        self.satellite_id = satellite_id
        self.connection_handler: Optional[SatelliteLinkHandler] = None

        self.sub_devices = [] # List of sub-devices managed by this satellite handler
        for device_name, device_type in connect_info.get("sub_devices", {}).items():
            satellite_device = SatelliteDevice(self, device_name, device_type)
            self.sub_devices.append(satellite_device)
            self.room_controller.attach_object(satellite_device)

    async def begin_handler(self, socket_reader: asyncio.StreamReader, socket_writer: asyncio.StreamWriter):
        """
        Begin handling the connection to the satellite device.
        This method sets up the connection handler for the satellite device.
        """
        self.connection_handler = SatelliteLinkHandler(socket_reader, socket_writer)
        await self.connection_handler.begin_handler(downlink_handler=self.on_downlink)
        return self.connection_handler

    async def new_connection(self, socket_reader: asyncio.StreamReader, socket_writer: asyncio.StreamWriter):
        """
        Handle a new connection to the satellite device.

        """
        if self.connection_handler is not None:
            logging.info(f"Closing existing connection for satellite {self.satellite_id}")
            await self.connection_handler.destroy()
        if socket_reader and socket_writer:
            self.connection_handler = SatelliteLinkHandler(socket_reader, socket_writer)
            await self.connection_handler.begin_handler(downlink_handler=self.on_downlink)
            logging.info(f"New connection established with satellite {self.satellite_id}")
        return None

    def send_uplink(self, device: RoomObject, event_name: str, *args, **kwargs):
        """
        Send a downlink message to the satellite device.

        :param device: The device to send the downlink message to.
        :param event_name: The name of the event to send.
        :param args: Any additional arguments to include in the message.
        :param kwargs: Any additional keyword arguments to include in the message.
        """
        if self.connection_handler and self.connection_handler.connection_alive():
            message = {
                "sub_device_id": device.device_id,
                "event_name": event_name,
                "args": args,
                "kwargs": kwargs
            }
            self.connection_handler.send_uplink(message)

    async def on_downlink(self, message):
        """
        Handle a downlink message from the satellite device.

        :param message: The message received from the satellite device.
        """
        data = json.loads(message)
        message_type = data.get("event", "unknown")
        devices = data.get("devices", {})
        for device_id, device_data in devices.items():
            # Find the corresponding sub-device
            sub_device = next((d for d in self.sub_devices if d.device_id == device_id), None)
            if sub_device:
                logging.info(f"Updated state for {sub_device.object_name}: {device_data}")
            else:
                logging.warning(f"Received data for unknown device ID: {device_id}")

    def online(self):
        """
        Check if the satellite handler is online.

        :return: True if the satellite handler is online, False otherwise.
        """
        return self.connection_handler is not None and self.connection_handler.connection_alive()















