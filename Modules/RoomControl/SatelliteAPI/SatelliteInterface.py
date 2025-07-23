import json

from urllib3 import connection_from_url

from Modules.RoomControl.SatelliteAPI.SatelliteDevice import SatelliteDevice
from Modules.RoomControl.SatelliteAPI.SatelliteHandler import SatelliteHandler
from Modules.RoomModule import RoomModule
import netifaces
import asyncio
from loguru import logger as logging

def get_host_names():
    """
    Gets all the ip addresses that can be bound to
    """
    interfaces = []
    for interface in netifaces.interfaces():
        try:
            if netifaces.AF_INET in netifaces.ifaddresses(interface):
                for link in netifaces.ifaddresses(interface)[netifaces.AF_INET]:
                    if link["addr"] != "":
                        interfaces.append(link["addr"])
        except Exception as e:
            logging.debug(f"Error getting interface {interface}: {e}")
            pass
    return interfaces

class SatelliteInterface(RoomModule):
    is_webserver = False
    requires_async = True

    def __init__(self, room_controller):
        super().__init__(room_controller)
        logging.info("Initializing Satellite Interface")
        self.room_controller = room_controller
        self.server = None
        self.server_address = get_host_names()
        self.server_port = 47670
        self.satellite_handlers = []

    async def start(self):
        self.server = await asyncio.start_server(
            self.datalink_connection_handler,
            host=self.server_address,
            port=self.server_port
        )
        logging.info(f"Starting satellite interface server on {self.server_address}:{self.server_port}")
        async with self.server:
            await self.server.serve_forever()

    async def datalink_connection_handler(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        """
        Handle setting up the persistent socket connection to the satellite device.
        """
        try:
            incoming_connection = writer.get_extra_info('peername')
            logging.info(f"Incoming connection from {incoming_connection[0]}:{incoming_connection[1]}")
            # Get the amount of data in the reader buffer
            data = await reader.readuntil(b'\0')  # Read until null byte, excluding it
            data = data[:-1]  # Remove the null byte
            msg_data = json.loads(data.decode('utf-8').strip())
            msg_type = msg_data.get("msg_type", "unknown")
            if msg_type != "device_info":
                logging.error(f"Unexpected message type from satellite: {msg_type}")
            existing_device = next((device for device in self.satellite_handlers if device.satellite_id == msg_data["name"]), None)
            if existing_device:
                logging.info(f"Satellite {msg_data['name']} reconnected")
                await existing_device.new_connection(reader, writer)
                return
            # Create a new SatelliteDevice instance
            satellite_device = SatelliteHandler(self.room_controller, msg_data)
            await satellite_device.begin_handler(reader, writer)
            self.satellite_handlers.append(satellite_device)
            logging.info(f"New satellite device connected: {satellite_device.satellite_id}")
        except Exception as e:
            logging.error(f"Error handling satellite connection: {e}")
            logging.exception(e)
            if writer:
                logging.info("Closing writer due to error")
                writer.close()
                await writer.wait_closed()
                logging.info("Writer closed")