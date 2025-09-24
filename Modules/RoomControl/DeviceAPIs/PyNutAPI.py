import sys
import time

from loguru import logger as logging

from Modules.RoomControl import background
from Modules.RoomModule import RoomModule
from Modules.RoomObject import RoomObject

try:
    from nut2 import PyNUTClient, PyNUTError
except ImportError:
    # Print the directory of the current python interpreter to determine where it's looking for packages
    pypath = sys.executable
    logging.error(f"PyNUT library not found in {pypath}, PyNutAPI will not function")
    PyNUTClient = None
    PyNUTError = None


status_lookup = {
    "ALARM": "ALARM",
    "BOOST": "Boosting",
    "BYPASS": "Bypass Active",
    "CAL": "Calibrating",
    "CHRG": "Charging",
    "COMM": "Communication?",
    "DISCHRG": "Discharging",
    "FSD": "Forced Shutdown",
    "LB": "Low Battery",
    "NOCOMM": "Comms Lost",
    "OB": "On Battery",
    "OFF": "Offline",
    "OL": "Online",
    "OVER": "OVERLOAD",
    "RB": "Replace Battery",
    "TEST": "Under Test",
    "TRIM": "Trim Active"
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
        if PyNUTClient is None:
            logging.error("PyNUT library not found, PyNutAPI will not function")
            return

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
        self.available_ups = self.get_available_ups_list()

        self.ups_data = {}

    def _connect(self):
        try:
            self.client = PyNUTClient(self.server_host, self.server_port,
                                      self.server_username, self.server_password)
            self.client._connect()
            logging.info(f"Connected to NUT server {self.server_name} at {self.server_host}:{self.server_port}")
        except PyNUTError as e:
            logging.error(f"Error connecting to NUT server {self.server_name}: {e}")
            self.client = None

    def get_available_ups_list(self):
        return self.client.list_ups()

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
                except PyNUTError as e:
                    if "BEGIN LIST UPS" in str(e):
                        self._connect()
                        continue
        return wrapper

    @nut_func
    def update_ups(self, ups):
        self.ups_data[ups] = self.client.list_vars(ups)

    def get_ups_data(self, ups):
        return self.ups_data.get(ups, {})

    def get_status(self, ups):
        status_list = self.get_ups_data(ups).get("ups.status", "UNKNOWN").split()
        if not status_list:
            return "UNKNOWN"
        final_status = ""
        for status in status_list:
            final_status += status_lookup.get(status, status) + ", "
        return final_status[:-2]  # Remove trailing comma and space


    def get_max_output(self, ups):
        return int(self.get_ups_data(ups).get("ups.realpower.nominal", 0))

    def get_output_watts(self, ups):
        max_watts = self.get_max_output(ups)
        load = int(self.get_ups_data(ups).get("ups.load", 0))
        if max_watts == 0 or load == 0:
            return 0
        return max_watts * (load / 100)

    def get_output_voltage(self, ups):
        return float(self.get_ups_data(ups).get("output.voltage", 0))

    def get_input_voltage(self, ups):
        return float(self.get_ups_data(ups).get("input.voltage", 0))

    def get_input_nominal(self, ups):
        return float(self.get_ups_data(ups).get("input.voltage.nominal", 0))

    def get_battery_charge(self, ups):
        return int(self.get_ups_data(ups).get("battery.charge", 0))

    def get_battery_voltage(self, ups):
        return float(self.get_ups_data(ups).get("battery.voltage", 0))

    def get_battery_nominal(self, ups):
        return float(self.get_ups_data(ups).get("battery.voltage.nominal", 0))

    def get_runtime_left(self, ups):
        return float(self.get_ups_data(ups).get("battery.runtime", 0))

    def get_beeper_status(self, ups):
        return self.get_ups_data(ups).get("ups.beeper.status", "unknown")

    def get_test_result(self, ups):
        return self.get_ups_data(ups).get("ups.test.result", "No test result available")

    @nut_func
    def execute_command(self, ups, command):
        return self.client.run_command(ups, command)

    @nut_func
    def force_shutdown(self, ups):
        return self.client.fsd(ups)

    def nut_online(self):
        """
        Check if the NUT server is online.
        :return: True if the server is online, False otherwise.
        """
        return self.client is not None

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
        except Exception as e:
            logging.error(f"Error checking UPS online status for {ups}: {e}")
            return False


class PyNutDevice(RoomObject):

    supported_actions = ["self_test_quick", "self_test_extended", "self_test_cancel", "shutdown", "silence_alarm"]

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
                logging.exception(e)
                logging.error(f"Error updating device info for {self.device_name}: {e}")
                time.sleep(30)
            finally:
                time.sleep(5)

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
        self.nut_server.update_ups(self.ups_name)
        if not self.nut_server.nut_online() or not self.nut_server.ups_online(self.ups_name):
            return
        else:
            self.device_info = {
                "status": self.nut_server.get_status(self.ups_name),
                "output_watts": self.nut_server.get_output_watts(self.ups_name),
                "output_voltage": self.nut_server.get_output_voltage(self.ups_name),
                "input_voltage": self.nut_server.get_input_voltage(self.ups_name),
                "input_nominal": self.nut_server.get_input_nominal(self.ups_name),
                "battery_charge": self.nut_server.get_battery_charge(self.ups_name),
                "battery_voltage": self.nut_server.get_battery_voltage(self.ups_name),
                "battery_nominal": self.nut_server.get_battery_nominal(self.ups_name),
                "runtime_remaining": self.nut_server.get_runtime_left(self.ups_name),
                "max_output": self.nut_server.get_max_output(self.ups_name),
                "test_result": self.nut_server.get_test_result(self.ups_name),
                "beeper_status": self.nut_server.get_beeper_status(self.ups_name)
            }

    def get_state(self):
        if not self.device_info:
            return {}
        return {
            "status": self.device_info["status"],
            "output_watts": self.device_info["output_watts"],
            "output_voltage": self.device_info["output_voltage"],
            "input_voltage": self.device_info["input_voltage"],
            "battery_charge": self.device_info["battery_charge"],
            "runtime_remaining": self.device_info["runtime_remaining"],
            "battery_voltage": self.device_info["battery_voltage"],
            "test_result": self.device_info["test_result"],
            "beeper_status": self.device_info["beeper_status"]
        }

    def get_info(self):
        if not self.device_info:
            return {}
        return {
            "battery_nominal": self.device_info["battery_nominal"],
            "max_output": self.device_info["max_output"],
            "input_nominal": self.device_info["input_nominal"],
        }

    def get_type(self):
        return "UPSDevice"

    @property
    def preform_action(self):
        return None

    @preform_action.setter
    def preform_action(self, action):
        if action not in self.supported_actions:
            logging.warning(f"Unsupported action '{action}' for device {self.device_name}")
            return
        logging.info(f"Preforming action '{action}' on device {self.device_name}")
        match action:
            case "self_test_quick":
                self.nut_server.execute_command(self.ups_name, "test.battery.start.quick")
            case "self_test_extended":
                self.nut_server.execute_command(self.ups_name, "test.battery.start.deep")
            case "self_test_cancel":
                self.nut_server.execute_command(self.ups_name, "test.battery.stop")
            case "shutdown":
                self.nut_server.execute_command(self.ups_name, "shutdown.return")
            case "silence_alarm":
                self.nut_server.execute_command(self.ups_name, "beeper.mute")
        logging.info(f"Action '{action}' completed on device {self.device_name}")

    @property
    def on_battery(self):
        if not self.device_info:
            return False
        return "On Battery" in self.device_info["status"]