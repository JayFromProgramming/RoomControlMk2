import json
import asyncio
from typing import Optional
from loguru import logger as logging
from Modules.RoomControl.SatelliteAPI.SatelliteDevice import SatelliteDevice
from Modules.RoomControl.SatelliteAPI.SatelliteMonitor import SatelliteMonitor
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
        :param connect_info: A dictionary containing connection information for the satellite device.
        """
        satellite_id = connect_info.get("name", "unknown_satellite")
        self.room_controller = room_controller
        self.satellite_id = satellite_id
        self.satellite_cpu_usage = 0
        self.satellite_uptime = 0
        self.satellite_free_heap = 0
        self.satellite_mcu_temp = 0
        self.satellite_signal_strength = 0
        self.satellite_firmware_version = "unknown"
        self.satellite_firmware_branch = "unknown"
        self.satellite_partition = "unknown"
        self.connection_handler: Optional[SatelliteLinkHandler] = None
        self.satellite_monitor = SatelliteMonitor(self, self.room_controller)
        self.sub_devices = [] # List of sub-devices managed by this satellite handler
        self._build(connect_info)

    def _build(self, connect_info):
        self.satellite_firmware_version = connect_info.get("version", "unknown")
        self.satellite_firmware_branch = connect_info.get("branch", "unknown")
        self.satellite_partition = connect_info.get("partition", "unknown")
        self.sub_devices = []  # List of sub-devices managed by this satellite handler
        for device_name, device_type in connect_info.get("sub_devices", {}).items():
            satellite_device = SatelliteDevice(self, device_name, device_type)
            self.sub_devices.append(satellite_device)
        logging.info(f"Initialized satellite handler for {self.satellite_id} with {len(self.sub_devices)} "
                     f"sub-devices running version {self.satellite_firmware_version} [{self.satellite_firmware_branch}]")

    def rebuild_device(self, connect_info):
        """
        Check if the satellite device is connected with new firmware.
        This method is intended to be called after the connection has been established.
        """
        logging.info(f"Rebuilding satellite handler for {self.satellite_id} with new firmware version {connect_info.get('version', 'unknown')}")
        # Delete all sub-device objects
        for sub_device in self.sub_devices:
            try:
                self.room_controller.detach_object(sub_device)
            except ValueError:
                pass
        self.sub_devices.clear()
        self._build(connect_info)

    async def preform_firmware_update(self, firmware_path: str):
        """
        Perform a firmware update on the satellite device.
        This method is intended to be called after the connection has been established.
        """
        return await self.connection_handler.uplink_new_firmware(firmware_path)

    async def begin_handler(self, socket_reader: asyncio.StreamReader, socket_writer: asyncio.StreamWriter):
        """
        Begin handling the connection to the satellite device.
        This method sets up the connection handler for the satellite device.
        """
        self.connection_handler = SatelliteLinkHandler(socket_reader, socket_writer)
        await self.connection_handler.begin_handler(self.on_downlink)
        return self.connection_handler

    async def new_connection(self, socket_reader: asyncio.StreamReader, socket_writer: asyncio.StreamWriter):
        """
        Handle a new connection to the satellite device.

        """
        if self.connection_handler is not None:
            await self.connection_handler.destroy()
        if socket_reader and socket_writer:
            self.connection_handler = SatelliteLinkHandler(socket_reader, socket_writer)
            await self.connection_handler.begin_handler(self.on_downlink)
            return True
        logging.error("Failed to create new connection handler: socket_reader or socket_writer is None")
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
                "sub_device_id": device.device_id.split(".")[-1],  # Get the sub-device ID from the full device ID
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
        # Determine if the message is a downlink or an event
        # This is indicated by the first byte of the message either being 'D' for downlink or 'E' for event
        data = json.loads(message)
        msg_type = data.get("msg_type", "unknown")
        if msg_type == "state_update":
            await self.parse_downlink(data)
        elif msg_type == "event":
            await self.parse_event(data)
        else:
            logging.warning(f"Received unknown message type: {msg_type}")

    async def parse_downlink(self, data):
        try:
            devices = data.get("objects", {})
            for device_id, device_data in devices.items():
                # Find the corresponding sub-device
                sub_device = next((d for d in self.sub_devices if d.device_id.split(".")[-1] == device_id), None)
                if sub_device:
                    # logging.info(f"Updating sub-device {sub_device.device_id} with data: {device_data}")
                    for key, value in device_data.items():
                        if key == "state":
                            for state_key, state_value in value.items():
                                sub_device.set_value(state_key, state_value)
                        elif key == "health":
                            sub_device._health = value
                        elif key == "actions":
                            sub_device.supported_actions = value
                else:
                    logging.warning(f"Received data for unknown device ID: {device_id}")
            # Update satellite handler state
            self.satellite_cpu_usage = data.get("mcu_load", 0)
            self.satellite_uptime = data.get("mcu_uptime", 0)
            self.satellite_free_heap = data.get("free_heap", 0)
            self.satellite_mcu_temp = data.get("mcu_temp", 0)
            self.satellite_signal_strength = data.get("sig_strength", 0)
        except Exception as e:
            logging.error(f"Error processing downlink message: {e}")
            logging.exception(e)

    async def parse_event(self, data):
        try:
            event_name = data.get("event", "unknown")
            args = data.get("args", [])
            kwargs = data.get("kwargs", {})
            sub_device_id = data.get("object", None)
            # logging.info(f"Received event {event_name} for sub-device {sub_device_id} with args: {args}, kwargs: {kwargs}")

            # Find the corresponding sub-device
            sub_device = next((d for d in self.sub_devices if d.device_id.split(".")[-1] == sub_device_id), None)
            if sub_device:
                sub_device.emit_event(event_name, *args, **kwargs)
            else:
                logging.warning(f"Received event for unknown device ID: {sub_device_id}")
        except Exception as e:
            logging.error(f"Error processing event message: {e}")
            logging.exception(e)

    def online(self):
        """
        Check if the satellite handler is online.

        :return: True if the satellite handler is online, False otherwise.
        """
        return self.connection_handler is not None and self.connection_handler.connection_alive()















