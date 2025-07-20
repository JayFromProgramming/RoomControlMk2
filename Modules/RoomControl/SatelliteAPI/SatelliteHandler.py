import json
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
        satellite_id = connect_info.get("device_id", "unknown_device")
        self.room_controller = room_controller
        self.satellite_id = satellite_id
        self.connection_handler: Optional[SatelliteLinkHandler] = None

        self.sub_devices = [] # List of sub-devices managed by this satellite handler
        for device in connect_info.get("sub_devices", []):
            device_id = device.get("device_id", "unknown_satellite_device")
            device_type = device.get("device_type", "unknown_device_type")
            satellite_device = SatelliteDevice(self, device_id, device_type)
            self.sub_devices.append(satellite_device)

    async def begin_handler(self, websocket_connection):
        """
        Begin handling the connection to the satellite device.
        This method sets up the connection handler for the satellite device.

        :param websocket_connection: The websocket connection to the satellite device.
        """
        self.connection_handler = SatelliteLinkHandler(websocket_connection)
        await self.connection_handler.begin_handler()
        self.room_controller.attach_object(self)
        return self.connection_handler

    async def new_connection(self, websocket_connection):
        """
        Handle a new connection to the satellite device.

        :param websocket_connection: The websocket connection to the satellite device.
        """
        if self.connection_handler is not None:
            if self.connection_handler.connection_alive():
                logging.warning(f"Satellite {self.satellite_id} already has an active connection.")
                return self.connection_handler
            await self.connection_handler.destroy()
            self.connection_handler = SatelliteLinkHandler(websocket_connection)
            await self.connection_handler.begin_handler()
            return self.connection_handler
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
                "device_id": device.object_id,
                "event_name": event_name,
                "args": args,
                "kwargs": kwargs
            }
            self.connection_handler.send_uplink(message)

    def on_downlink(self, message):
        """
        Handle a downlink message from the satellite device.

        :param message: The message received from the satellite device.
        """
        data = json.loads(message)
        devices = data.get("devices", {})


    def online(self):
        """
        Check if the satellite handler is online.

        :return: True if the satellite handler is online, False otherwise.
        """
        return self.connection_handler is not None and self.connection_handler.connection_alive()















