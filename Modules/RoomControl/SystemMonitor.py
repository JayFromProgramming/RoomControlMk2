import socket
import time

from Modules.RoomControl import background
from Modules.RoomModule import RoomModule
from Modules.RoomObject import RoomObject

import psutil
import os
import subprocess
from loguru import logger as logging


class SystemMonitor(RoomModule):
    is_promise = False
    is_webserver = False

    def __init__(self, room_controller):
        RoomModule.__init__(self, room_controller)
        self.room_controller = room_controller
        self.database = room_controller.database
        self.system_status = None
        self.monitors = []
        self.monitors.append(SystemMonitorLocal(room_controller))
        self.monitors.append(SystemMonitorRemote(room_controller, "WOPR"))

        for monitor in self.monitors:
            self.room_controller.attach_object(monitor)


class SystemMonitorLocal(RoomObject):

    def __init__(self, room_controller):
        super().__init__("SystemMonitor-Master", "SystemMonitor")
        self.room_controller = room_controller
        self.set_value("name", "Master Controller")
        self.set_value("cpu_usage", 0)
        self.set_value("memory_usage", 0)
        self.set_value("disk_usage", 0)
        self.set_value("network_usage", 0)
        self.set_value("address", None)
        self.last_network_usage = 0
        self.set_value("temperature", 0)
        self.set_value("update_available", None)
        self.set_value("uptime_system", round(time.time() - psutil.boot_time()))
        self.set_value("uptime_controller", round(time.time() - os.path.getmtime("main.py")))
        self.latest = None
        self.check_version()
        self.start_monitoring()
        self.room_controller.attach_object(self)

    def get_state(self):
        return self.get_values()

    def get_health(self):
        return {
            "online": True,
            "fault": False,
            "reason": ""
        }

    def get_type(self):
        return self.object_type

    @property
    def action(self):
        return None

    @action.setter
    def action(self, value):
        if value == "reboot":
            self.reboot()
        if value == "shutdown":
            self.shutdown()
        if value == "update":
            self.update_system()
        if value == "restart":
            self.restart()

    def reboot(self):
        logging.info("Rebooting system on SystemMonitor request")
        subprocess.run(["sudo", "reboot"])

    def shutdown(self):
        logging.info("Shutting down system on SystemMonitor request")
        subprocess.run(["sudo", "shutdown", "now"])

    def update_system(self):
        logging.info("Updating system on SystemMonitor request")
        subprocess.run(["sudo", "apt", "update"])
        subprocess.run(["sudo", "apt", "upgrade", "-y"])
        subprocess.run(["sudo", "apt", "autoremove", "-y"])
        subprocess.run(["sudo", "apt", "clean"])
        subprocess.run(["git", "pull", "origin", "mk3"])
        exit(-1)

    def restart(self):
        logging.info("Restarting system on SystemMonitor request")
        exit(-1)

    @staticmethod
    def get_ip():
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0)
        try:
            # doesn't even have to be reachable
            s.connect(('10.254.254.254', 1))
            IP = s.getsockname()[0]
        except Exception:
            IP = '127.0.0.1'
        finally:
            s.close()
        return IP

    @background
    def check_version(self):
        while True:
            # Check if the current version is the latest (use git to check if the current commit is the latest)
            try:
                # Get the branch we are on
                result = subprocess.run(["git", "branch", "--show-current"], capture_output=True)
                branch = str(result.stdout).strip().strip("b'").strip("\\n")
                # Fetch the latest commits
                subprocess.run(["git", "fetch", "origin", branch])
                # Check if we are behind the latest commit
                result = subprocess.run(["git", "rev-list", "--count", f"HEAD..origin/{branch}"], capture_output=True)
                if str(result.stdout) == b'0\n':
                    self.latest = False
                self.latest = True
            except Exception as e:
                logging.error(f"Error checking for updates: {e}")
                self.latest = None
            finally:
                time.sleep(60)
            self.set_value("update_available", self.latest)

    @background
    def start_monitoring(self):
        while True:
            try:
                cpu_usage = psutil.cpu_percent()
                memory_usage = psutil.virtual_memory().percent
                disk_usage = psutil.disk_usage('/').percent
                if hasattr(psutil, "sensors_temperatures"):
                    sys_temp = psutil.sensors_temperatures()
                    # logging.info(sys_temp)
                    if "cpu_thermal" in sys_temp:
                        cpu_temp = round(sys_temp["cpu_thermal"][0].current)
                    elif "coretemp" in sys_temp:
                        cpu_temp = round(sys_temp["coretemp"][0].current)
                    else:
                        cpu_temp = None
                else:
                    cpu_temp = None
                network_usage = psutil.net_io_counters().bytes_sent - self.last_network_usage
                self.last_network_usage = psutil.net_io_counters().bytes_sent

                self.set_value("cpu_usage", cpu_usage)
                self.set_value("memory_usage", memory_usage)
                self.set_value("disk_usage", disk_usage)
                self.set_value("network_usage", network_usage)
                self.set_value("temperature", cpu_temp)
                self.set_value("uptime_system", round(time.time() - psutil.boot_time()))
                self.set_value("uptime_controller", round(time.time() - os.path.getmtime("main.py")))
                self.set_value("address", self.get_ip())

            except Exception as e:
                logging.error(f"Error: {e}")
                logging.exception(e)
            finally:
                time.sleep(5)


class SystemMonitorRemote(RoomObject):

    def __init__(self, room_controller, satellite_name):
        super().__init__(f"SystemMonitor-{satellite_name}",
                         "SystemMonitor")
        self.satellite_monitor = room_controller.get_object(f"RemoteMonitor-{satellite_name}")
        # This object is almost a copy of the object from the satellite but with some extra methods
        self.set_value("name", satellite_name)
        # Set all the values from the satellite monitor
        self.set_value("cpu_usage", self.satellite_monitor.get_value("cpu_usage"))
        self.set_value("memory_usage", self.satellite_monitor.get_value("memory_usage"))
        self.set_value("disk_usage", self.satellite_monitor.get_value("disk_usage"))
        self.set_value("network_usage", self.satellite_monitor.get_value("network_usage"))
        self.set_value("address", self.satellite_monitor.get_value("address"))
        self.set_value("temperature", self.satellite_monitor.get_value("temperature"))
        self.set_value("uptime_system", self.satellite_monitor.get_value("uptime_system"))
        self.set_value("uptime_controller", self.satellite_monitor.get_value("uptime_controller"))
        self.set_value("update_available", self.satellite_monitor.get_value("update_available"))

        # Check if the object is not a promise object
        self.online = not self.satellite_monitor.is_promise
        self.update()

    def get_state(self):
        return self.get_values()

    def get_health(self):
        return {
            "online": self.online,
            "fault": False,
            "reason": ""
        }

    @property
    def action(self):
        return None

    @action.setter
    def action(self, value):
        if value == "reboot":
            self.satellite_monitor.emit_event("reboot")
        if value == "shutdown":
            self.satellite_monitor.emit_event("shutdown")
        if value == "update":
            self.satellite_monitor.emit_event("update")
        if value == "restart":
            self.satellite_monitor.emit_event("restart")

    @background
    def update(self):
        while True:
            if self.satellite_monitor.is_promise:
                self.online = False
            else:
                self.online = True
                self.set_value("cpu_usage", self.satellite_monitor.get_value("cpu_usage"))
                self.set_value("memory_usage", self.satellite_monitor.get_value("memory_usage"))
                self.set_value("disk_usage", self.satellite_monitor.get_value("disk_usage"))
                self.set_value("network_usage", self.satellite_monitor.get_value("network_usage"))
                self.set_value("address", self.satellite_monitor.get_value("address"))
                self.set_value("temperature", self.satellite_monitor.get_value("temperature"))
                self.set_value("uptime_system", self.satellite_monitor.get_value("uptime_system"))
                self.set_value("uptime_controller", self.satellite_monitor.get_value("uptime_controller"))
                self.set_value("update_available", self.satellite_monitor.get_value("update_available"))
            time.sleep(5)

    def get_type(self):
        return self.object_type
