import json

from Modules.RoomControl.SatelliteAPI.SatelliteDevice import SatelliteDevice
from Modules.RoomModule import RoomModule
import netifaces
from aiohttp import web, WSCloseCode
from aiohttp import request
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
    is_webserver = True

    def __init__(self, room_controller):
        super().__init__(room_controller)
        logging.info("Initializing Satellite Interface")
        self.room_controller = room_controller

        self.app = web.Application()
        # Note: Uplink is from the perspective of the satellite to the server (e.g. sending data, events, etc.)
        # Downlink is from the perspective of the server to the satellite (e.g. sending commands, updates, etc.)
        self.app.add_routes([
            web.get("/sat_datalink", self.datalink_connection_handler)
        ])
        # Satellites will host their own webserver to receive commands from the server they will have these routes:
        # POST - /downlink - To receive commands from the server
        # GET  - /uplink   - For the server to poll the satellite for data
        # POST - /event    - For the server to send events to the satellite

        self.runner = web.AppRunner(self.app, access_log=None)
        self.webserver_address = get_host_names()
        self.webserver_port = 47670

        self.satellite_devices = []
        logging.info(f"Satellite Interface initialized with webserver on {self.webserver_address}:{self.webserver_port}")


    async def datalink_connection_handler(self, inbound_request):
        """
        Handle setting up the persistent websocket connection the satellite device
        """
        logging.info(f"Received connection request from satellite: {inbound_request.remote}")
        ws = web.WebSocketResponse()
        await ws.prepare(inbound_request)
        logging.info(f"Satellite connected: {inbound_request.remote}")
        # Receive the first message from the satellite to get the device information
        msg = await ws.receive()
        if msg.type == web.WSMsgType.TEXT:
            msg_data = json.loads(msg.data)
            msg_type = msg_data.get("msg_type", "unknown")
            if msg_type != "connection_info":
                logging.error(f"Unexpected message type from satellite: {msg_type}")
                await ws.close(code=WSCloseCode.PROTOCOL_ERROR, message=b"Unexpected message type")
                return ws
            logging.info(f"Received initial message from satellite: {msg.data}")
            # Look through the list of satellite devices to see if this one already exists and if so replace it's connection handler
            existing_device = next((device for device in self.satellite_devices if device.device_id == msg_data["device_id"]), None)
            if existing_device:
                logging.info(f"Satellite {msg_data['device_id']} reconnected")
                await existing_device.new_connection(ws)
                return ws
            # Create a new SatelliteDevice instance
            satellite_device = SatelliteDevice(self.room_controller, msg_data)
            await satellite_device.begin_handler(ws)
            self.satellite_devices.append(satellite_device)
            logging.info(f"New satellite device connected: {satellite_device.device_id}")
        else:
            logging.error("Failed to receive initial message from satellite")
            await ws.close(code=WSCloseCode.PROTOCOL_ERROR, message=b"Failed to receive initial message from satellite")
        return ws

