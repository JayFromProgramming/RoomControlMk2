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
        self.last_network_usage = 0
        self.set_value("temperature", 0)
        self.set_value("update_available", False)
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

    @background
    def check_version(self):
        while True:
            # Check if the current version is the latest (use git to check if the current commit is the latest)
            try:
                subprocess.run(["git", "fetch", "origin", "master"])
                result = subprocess.run(["git", "rev-list", "--count", "HEAD..origin/master"], capture_output=True)
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
            cpu_usage = psutil.cpu_percent()
            memory_usage = psutil.virtual_memory().percent
            disk_usage = psutil.disk_usage('/').percent
            if hasattr(psutil, "sensors_temperatures"):
                sys_temp = psutil.sensors_temperatures()
                if "cpu_thermal" in sys_temp:
                    cpu_temp = round(sys_temp["cpu_thermal"][0].current)
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
            time.sleep(5)


class SystemMonitorRemote(RoomObject):

    def __init__(self, room_controller, satellite_name):
        super().__init__("SystemMonitor", "SystemMonitor")
        self.satellite_monitor = room_controller.get_object(f"SystemMonitor-{satellite_name}")
        # This object is almost a copy of the object from the satellite but with some extra methods
        self.set_value("name", satellite_name)
        # Set all the values from the satellite monitor
        self.set_value("cpu_usage", self.satellite_monitor.get_value("cpu_usage"))
        self.set_value("memory_usage", self.satellite_monitor.get_value("memory_usage"))
        self.set_value("disk_usage", self.satellite_monitor.get_value("disk_usage"))
        self.set_value("network_usage", self.satellite_monitor.get_value("network_usage"))

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
