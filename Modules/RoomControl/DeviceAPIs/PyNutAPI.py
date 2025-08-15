import time

from loguru import logger as logging

from Modules.RoomControl import background
from Modules.RoomModule import RoomModule
from Modules.RoomObject import RoomObject

from nut2 import PyNUTClient, PyNUTError


status_lookup = {
    "ALARM": "ALARM",
    "BOOST": "Voltage Boost Active",
    "BYPASS": "Bypass Active",
    "CAL": "Runtime Calibration",
    "CHRG": "Battery Charging",
    "COMM": "Communications Active",
    "DISCHRG": "Battery Discharging",
    "FSD": "Forced Shutdown",
    "LB": "Low Battery",
    "NOCOMM": "Communications Lost",
    "OB": "On Battery",
    "OFF": "Offline",
    "OL": "Online",
    "OVER": "Overloaded",
    "RB": "Battery Needs Replaced",
    "TEST": "Under Test",
    "TRIM": "Voltage Trim Active"
}



class PyNutAPI(RoomModule):
    """
    PyNutAPI is a module for interacting with PyNut devices.
    It extends the RoomModule class and provides methods to manage PyNut devices.
    """

    def __init__(self, room_controller):
        super().__init__(room_controller)
        self.room_controller = room_controller
        self.database = room_controller.database
        self.init_database()

        self.nut_clients = {}
        for row in self.database.get_table("nut_servers").get_all():
            client = PyNutServer(row["server_name"], row['server_host'], row['server_port'], row['server_username'],
                                 row['server_password'])
            self.nut_clients[row['server_name']] = client

        self.nut_devices = []
        for row in self.database.get_table("nut_devices").get_all():
            if row['ups_server'] in self.nut_clients:
                try:
                    nut_client = self.nut_clients[row['ups_server']]
                    device = PyNutDevice(self.room_controller, nut_client, row['ups_name'])
                    self.nut_devices.append(device)
                    logging.info(f"Added NUT device {row['ups_name']} on server {row['ups_server']}")
                except PyNUTError as e:
                    logging.error(f"Error adding NUT device {row['ups_name']} on server {row['ups_server']}: {e}")
            else:
                logging.warning(f"NUT server {row['ups_server']} not found for device {row['ups_name']}")


    def init_database(self):
        """
        Initialize the database for PyNutAPI.
        This method creates the necessary tables for storing device information.
        """
        self.database.create_table("nut_servers", {
            "server_name": "TEXT",
            "server_host": "TEXT",
            "server_port": "INTEGER",
            "server_username": "TEXT",
            "server_password": "TEXT"
        }, primary_keys=["server_name"])
        self.database.create_table("nut_devices", {
            "ups_server": "TEXT",
            "ups_name": "TEXT",
        }, primary_keys=["ups_server", "ups_name"])

    def wait_for_ready(self):
        pass

class PyNutServer:

    def __init__(self, server_name, server_host, server_port, server_username, server_password):
        self.server_name = server_name
        self.server_host = server_host
        self.server_port = server_port
        self.server_username = server_username
        self.server_password = server_password
        self.client = None
        self._connect()
        logging.info(f"Initialized NUT server {self.server_name} at {self.server_host}:{self.server_port}")

    def _connect(self):
        try:
            self.client = PyNUTClient(self.server_host, self.server_port,
                                      self.server_username, self.server_password)
            self.client._connect()
            logging.info(f"Connected to NUT server {self.server_name} at {self.server_host}:{self.server_port}")
        except PyNUTError as e:
            logging.error(f"Error connecting to NUT server {self.server_name}: {e}")
            self.client = None

    @staticmethod
    def nut_func(func):
        def wrapper(self, *args, **kwargs):
            while True:
                try:
                    if self.client is None:
                        self._connect()
                    return func(self, *args, **kwargs)
                except EOFError:
                    self._connect()
                    continue
        return wrapper

    @nut_func
    def get_output_watts(self, ups):
        max_watts = int(self.client.get(ups, "ups.realpower.nominal"))
        return max_watts * (int(self.client.get(ups, "ups.load")) / 100.0)

    @nut_func
    def get_output_voltage(self, ups):
        return float(self.client.get(ups, "output.voltage"))

    @nut_func
    def get_input_voltage(self, ups):
        return float(self.client.get(ups, "input.voltage"))

    @nut_func
    def get_battery_charge(self, ups):
        return float(self.client.get(ups, "battery.charge"))

    @nut_func
    def get_runtime_left(self, ups):
        return float(self.client.get(ups, "battery.runtime"))

    def nut_online(self):
        """
        Check if the NUT server is online.
        :return: True if the server is online, False otherwise.
        """
        return self.client is not None and self.client.is_connected()

    def ups_online(self, ups):
        """
        Check if the specified UPS is connected
        :param ups: The name of the UPS to check.
        :return: True if the UPS is online, False otherwise.
        """
        try:
            avail_ups = self.client.list_ups()
            return ups in avail_ups
        except PyNUTError:
            return False


class PyNutDevice(RoomObject):

    """
    Represents a PyNut device in the room control system.
    This class is used to manage the PyNut device's state and interactions.
    """

    def __init__(self, room_controller, nut_server, ups_name):
        self.device_name = f"{nut_server.server_name}.{ups_name}"
        super().__init__(self.device_name, "UPSDevice")
        self.room_controller = room_controller
        self.nut_server = nut_server
        self.ups_name = ups_name
        self.device_info = None
        self.update_loop()
        self.room_controller.attach_object(self)

    @background
    def update_loop(self):
        while True:
            try:
                self.update_device_info()
            except Exception as e:
                logging.error(f"Error updating device info for {self.device_name}: {e}")
                time.sleep(60)

    def get_health(self):
        online = self.nut_server.nut_online() and self.nut_server.ups_online(self.ups_name)
        fault = self.device_info.get("fault", False) if self.device_info else False
        reason = ""
        if not self.nut_server.nut_online():
            reason = f"NUT server [{self.nut_server.server_name}] is offline"
        elif not self.nut_server.ups_online(self.ups_name):
            reason = f"UPS [{self.ups_name}] is offline"
        return {
            "online": online,
            "fault": fault,
            "reason": reason
        }

    def update_device_info(self):
        if not self.nut_server.nut_online() or not self.nut_server.ups_online(self.ups_name):
            self.device_info = {
                "status": "OFFLINE",
                "output_watts": 0,
                "output_voltage": 0,
                "input_voltage": 0,
                "battery_charge": 0,
                "runtime_left": 0,
            }
            return
        else:
            self.device_info = {
                "status": self.nut_server.client.get(self.ups_name, "ups.status"),
                "output_watts": self.nut_server.get_output_watts(self.ups_name),
                "output_voltage": self.nut_server.get_output_voltage(self.ups_name),
                "input_voltage": self.nut_server.get_input_voltage(self.ups_name),
                "battery_charge": self.nut_server.get_battery_charge(self.ups_name),
                "runtime_left": self.nut_server.get_runtime_left(self.ups_name),
            }
            self.set_value("status", status_lookup.get(self.device_info["status"], "Unknown"))
            self.set_value("output_watts", self.device_info["output_watts"])
            self.set_value("output_voltage", self.device_info["output_voltage"])
            self.set_value("input_voltage", self.device_info["input_voltage"])
            self.set_value("battery_charge", self.device_info["battery_charge"])
            self.set_value("runtime_left", self.device_info["runtime_left"])