import time

from Modules.RoomControl import background
from Modules.RoomObject import RoomObject
from loguru import logger as logging

class SatelliteMonitor(RoomObject):
    """
    Monitors the status of satellite devices.
    """

    def __init__(self, satellite_device, room_controller):
        super().__init__(satellite_device.satellite_id, "SatelliteMonitor")
        self.satellite_device = satellite_device
        self.room_controller = room_controller
        self.set_value("name", satellite_device.satellite_id)
        self.set_value("cpu_usage", 0)
        self.set_value("memory_usage", 0)
        self.set_value("disk_usage", 0)
        self.set_value("firmware_version", satellite_device.satellite_firmware_version)
        self.set_value("boot_partition", satellite_device.satellite_partition)
        self.set_value("address", None)
        self.last_network_usage = 0
        self.set_value("temperature", 0)
        self.set_value("update_available", None)
        self.set_value("uptime_mcu", 0)
        self.set_value("uptime_connection", 0)

        self.running = True
        self.update_loop()  # Start the background update loop
        self.room_controller.attach_object(self)

    @background
    def update_loop(self):
        """
        Periodically updates the satellite monitor's status.
        This method runs in the background to keep the monitor updated.
        """
        while self.running:
            self.update_status()
            time.sleep(15)

    def update_status(self):
        """
        Update the status of the satellite monitor.
        This method retrieves the latest status from the satellite device.
        """
        if self.satellite_device.online:
            self.set_value("cpu_usage", self.satellite_device.satellite_cpu_usage)
            self.set_value("memory_usage", self.satellite_device.satellite_free_heap)
            self.set_value("firmware_version", self.satellite_device.satellite_firmware_version)
            self.set_value("boot_partition", self.satellite_device.satellite_partition)
            self.set_value("temperature", self.satellite_device.satellite_mcu_temp)
            self.set_value("uptime_mcu", self.satellite_device.satellite_uptime)
            if self.satellite_device.connection_handler is None:
                # logging.warning(f"Satellite {self.satellite_device.satellite_id} has no connection handler.")
                self.set_value("uptime_connection", 0)
                self.set_value("address", None)
            else:
                self.set_value("uptime_connection", self.satellite_device.connection_handler.uptime)
                self.set_value("address", self.satellite_device.connection_handler.address)
            # Add more fields as needed
        else:
            logging.warning(f"Satellite {self.satellite_device.satellite_id} is not connected.")

    def get_state(self):
        return self.get_values()

    def get_type(self):
        return self.object_type