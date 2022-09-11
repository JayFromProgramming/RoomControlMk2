import logging
import typing

from pyvesync import VeSync
import asyncio
from threading import Thread

from Modules.RoomControl.AbstractSmartDevices import AbstractToggleDevice, background

logging = logging.getLogger(__name__)


class VeSyncAPI:

    def __init__(self, database):

        self.database = database

        email = self.database.cursor().execute("SELECT * FROM secrets WHERE secret_name = 'VesyncUsername'").fetchone()[1]
        password = self.database.cursor().execute("SELECT * FROM secrets WHERE secret_name = 'VesyncPassword'").fetchone()[1]
        self.database.cursor().close()
        self.manager = VeSync(email, password, time_zone='America/New_York')
        self.manager.login()

        self.manager.update()  # Populate the devices list

        self.devices = []
        for device in self.manager.outlets:
            self.devices.append(VeSyncPlug(device))

    def set_all_on(self, on: bool):
        for device in self.devices:
            device.set_on(on)

    def get_all_status(self):
        all_status = {}
        for device in self.devices:
            all_status[device.device_name] = device.get_status()
        return all_status

    def get_device(self, device_name):
        for device in self.devices:
            if device.device_name == device_name:
                return device
        return None

    def get_all_devices(self):
        return self.devices

    @background
    def refresh(self):
        for device in self.devices:
            device.refresh_info()


class VeSyncPlug(AbstractToggleDevice):

    def __init__(self, device):
        super().__init__()
        self.device = device
        self.device_name = device.device_name
        self.cached_details = {}
        self.online = True

    def name(self):
        return self.device_name

    @background
    def set_on(self, on: bool):
        logging.debug(f"Setting {self.device_name} to {on}")
        self.device.turn_on() if on else self.device.turn_off()

    @background
    def refresh_info(self):
        logging.debug(f"Refreshing {self.device_name} info")
        self.device.update()

    def get_status(self):
        if len(self.device.details) > 1:
            details = self.device.details
            details.update({"connection": "online"})
            return details
        else:
            return {"active_time": 0, "energy": 0, "power": 0, "voltage": 0, "connection": "offline"}

    def __str__(self):
        return f"{self.device_name}: {self.get_status()}"

    def __repr__(self):
        return self.__str__()
