import asyncio
import time

from Modules.RoomModule import RoomModule
import netifaces
from aiohttp import web
from aiohttp import request
from loguru import logger as logging

from Modules.RoomObject import RoomObject


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


class SatelliteObject(RoomObject):
    is_promise = False

    def __init__(self, object_name, object_type, satellite):
        super().__init__(object_name, object_type)
        self.satellite = satellite

    def get_state(self):
        return self.get_values()

    def get_type(self):
        return self.object_type

    def emit_event(self, event_name, *args, **kwargs):
        """
        Emit an event to all attached callbacks
        :param event_name: The name of the event to emit
        :param args: Any arguments to pass to the callback
        :param kwargs: Any keyword arguments to pass to the callback
        """
        asyncio.create_task(self.satellite.downlink_event(self, event_name, *args, **kwargs))

    def get_health(self):
        online = self.satellite.online and self._health.get("online", False)
        fault = self._health.get("fault", False)
        reason = self._health.get("reason", "") if self.satellite.online else "Satellite Host Offline"
        return {
            "online": online,
            "fault": fault,
            "reason": reason
        }


class Satellite:

    def __init__(self, name, ip, auth, room_controller):
        self.name = name
        self.ip = ip
        self.auth = auth
        self.last_seen = 0
        self.objects = []  # type: list[RoomObject]
        self.room_controller = room_controller

    @property
    def online(self):
        return self.last_seen > 0 and self.last_seen > time.time() - 60

    def attach_object(self, object_name, object_type):
        """
        Check if the objet already exists in the room as a promise object
        if so create a new object and attach it to the room controller
        """
        obj = self.room_controller.get_object(object_name, False)
        if obj is not None:
            if obj.object_type == "RoomObject" or obj.object_type == "promise":
                new_obj = SatelliteObject(object_name, f"satellite_{object_type}", self)
                self.room_controller.attach_object(new_obj)
                self.objects.append(new_obj)
                return new_obj
            else:
                if obj.object_type != f"satellite_{object_type}":
                    logging.warning(f"Object {object_name} already exists but is not of type {object_type} but"
                                    f" it is type {obj.object_type}")
                self.objects.append(obj)
                return obj
        else:
            new_obj = SatelliteObject(object_name, f"satellite_{object_type}", self)
            self.room_controller.attach_object(new_obj)
            self.objects.append(new_obj)
            return new_obj

    def update_object(self, object_name, data):
        """
        Update the object with new data
        """
        # Check if we've already created the object
        if object_name not in [obj.object_name for obj in self.objects]:
            self.attach_object(object_name, data["type"])
        for obj in self.objects:
            if obj.object_name == object_name:
                obj.update(data)
                return True
        return False

    def parse_uplink(self, data):
        """
        Parses the uplink data from the satellite
        """
        if data["name"] != self.name:
            logging.warning(f"Received uplink data from {data['name']} but expected {self.name}")
            return
        self.last_seen = time.time()
        for object_name, object_data in data["objects"].items():
            if not self.update_object(object_name, object_data):
                logging.warning(f"Received data for object {object_name} but it does not exist")
        self.ip = data["current_ip"]
        self.ip = str(self.ip).strip("'")
        self.room_controller.database.run("UPDATE satellites SET last_seen = ? WHERE name = ?",
                                          (self.last_seen, self.name))

    def parse_event(self, data):
        """
        Parses the event data from the satellite
        """
        if data["name"] != self.name:
            logging.warning(f"Received event data from {data['name']} but expected {self.name}")
            return
        self.last_seen = time.time()
        for obj in self.objects:
            if obj.object_name == data["object"]:
                logging.info(f"Received event {data['event']} from {data['object']}")
                obj.emit_event(data["event"], *data["args"], **data["kwargs"])
                return
        logging.warning(f"Received event data for object {data['object']} but it does not exist")

    async def auto_poll(self):
        """
        If last seen is more than 45 seconds ago, make a poll request to the satellite, if no response is received
        mark the satellite as offline and continue to poll every 60 seconds
        """
        while True:
            if self.ip is None:
                await asyncio.sleep(60)
                continue
            if self.last_seen < time.time() - 45:
                logging.info(f"Polling satellite {self.name} at {self.ip} due to a lack of response")
                # Poll the satellite
                async with request("GET", f"http://{self.ip}:47670/uplink") as response:
                    if response.status != 200:
                        pass
                    else:
                        self.parse_uplink(await response.json())
            await asyncio.sleep(60)

    async def downlink_event(self, object_ref, event_name, *args, **kwargs):
        """
        Send an event to the satellite
        """
        if not self.online:
            logging.warning(f"Cannot send event to {self.name} because it is offline")
            return
        data = {
            "name": self.name,
            "current_ip": self.ip,
            "object": object_ref.name(),
            "event": event_name,
            "args": args,
            "kwargs": kwargs,
            "auth": self.auth
        }
        logging.info(f"Sending event {event_name} to {self.name} @ {self.ip}:47670")
        if self.ip is None:
            logging.warning(f"Cannot send event to {self.name} because it does not have an IP address")
            return
        async with request("POST", f"http://{self.ip}:47670/event", json=data) as response:
            if response.status != 200:
                logging.warning(f"Failed to send event to {self.name} with status {response.status}")


class SatelliteInterface(RoomModule):
    is_webserver = True

    def __init__(self, room_controller):
        super().__init__(room_controller)
        self.room_controller = room_controller

        self.app = web.Application()
        # Note: Uplink is from the perspective of the satellite to the server (e.g. sending data, events, etc.)
        # Downlink is from the perspective of the server to the satellite (e.g. sending commands, updates, etc.)
        self.app.add_routes([
            web.post('/uplink', self.uplink_data),  # How the satellite will send data to the server
            # web.get('/downlink', self.downlink_poll),  # How the satellite will request information from the server
            web.post('/event', self.uplink_event),  # How the satellite will send events to the server
        ])
        # Satellites will host their own webserver to receive commands from the server they will have these routes:
        # POST - /downlink - To receive commands from the server
        # GET  - /uplink   - For the server to poll the satellite for data
        # POST - /event    - For the server to send events to the satellite

        self.runner = web.AppRunner(self.app, access_log=None)
        self.webserver_address = get_host_names()
        self.webserver_port = 47670

        self.init_database()

        self.satellites = {}
        self.load_satellites()

    def init_database(self):
        self.room_controller.database.execute("CREATE TABLE IF NOT EXISTS satellites"
                                              " (name TEXT PRIMARY KEY, ip TEXT, last_seen INTEGER, auth TEXT)")

    def load_satellites(self):
        results = self.room_controller.database.get("SELECT * FROM satellites")
        for name, ip, last_seen, auth in results:
            logging.info(f"Loading satellite {name} at {ip} with last seen {last_seen}")
            self.satellites[name] = Satellite(name, ip, auth, self.room_controller)
            self.satellites[name].last_seen = last_seen

    async def get_site(self):
        await self.runner.setup()
        site = web.TCPSite(self.runner, self.webserver_address, self.webserver_port)
        return site

    async def uplink_data(self, request):
        """
        Called by a satellite to send data to the server (e.g. sensor data, state changes)
        The json payload should contain the following:
        {
            "name": "Name of the satellite",
            "current_ip": "Current IP address of the satellite",
            "objects": {
                "object_name": {
                    "type": "Type of object",
                    "data": {
                        "key": "value"
                    },
                    "health": {
                        "online": "Boolean",
                        "fault": "Boolean",
                        "reason": "Reason for fault"
                    }
                }
            },
            "auth": "Authentication token"
        }
        """
        payload = await request.json()
        for satellite in self.satellites.values():
            if satellite.auth == payload["auth"]:
                satellite.parse_uplink(payload)
                return web.Response(status=200)
        return web.Response(status=401)

    async def uplink_event(self, request):
        """
        Called by a satellite to send an event to the server (e.g. motion detected, button pressed, switch state change)
        The json payload should contain the following:
        {
            "name": "Name of the satellite",
            "current_ip": "Current IP address of the satellite",
            "object": "Name of the object that emitted the event",
            "event": "Name of the event",
            "args": "List of arguments",
            "kwargs": "Dictionary of keyword arguments",
            "auth": "Authentication token"
        }
        """
        payload = await request.json()
        for satellite in self.satellites.values():
            if satellite.auth == payload["auth"]:
                satellite.parse_event(payload)
                return web.Response(status=200)
        return web.Response(status=401)
