import datetime
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
            self.devices.append(VeSyncPlug(device, self.database))

    def wait_for_ready(self):
        while not len(self.devices) > 0:
            pass

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
    def refresh_all(self):
        for device in self.devices:
            device.refresh_info()


class VeSyncPlug(AbstractToggleDevice):

    def __init__(self, device, database):
        super().__init__()
        self.device = device
        self.device_name = device.device_name
        self.cached_details = {}
        self.online = True
        self.fault = False
        self.last_update = datetime.datetime.now()
        self.database = database

        self.upper_bounds = None
        self.lower_bounds = None
        self.get_bounds()

    def get_bounds(self):
        """Gets expected power draw bounds from the DB"""
        cursor = self.database.cursor()
        cursor.execute("SELECT upper_bound, lower_bound FROM vesync_device_bounds WHERE device_name = ?", (self.device_name,))
        bounds = cursor.fetchone()
        cursor.close()
        if bounds:
            logging.info(f"VeSyncAPI ({self.device_name}): Bounds found in DB: {bounds}")
            self.upper_bounds = bounds[0]
            self.lower_bounds = bounds[1]
        else:
            logging.info(f"VeSyncAPI ({self.device_name}): No bounds found in DB, setting to None")
            self.upper_bounds = None
            self.lower_bounds = None

    def name(self):
        return self.device_name

    def is_on(self):
        return self.device.is_on

    @background
    def set_on(self, on: bool):
        logging.debug(f"Setting {self.device_name} to {on}")
        self.device.turn_on() if on else self.device.turn_off()

    @background
    def refresh_info(self):
        logging.debug(f"Refreshing {self.device_name} info")
        self.device.get_details()
        self.device.update()
        if self.upper_bounds and self.lower_bounds:
            state = self.get_info()
            if state["active_time"] < 2:  # If the device has been on for less than 2 minutes
                self.fault = False
                return    # Its power draw is probably not accurate
            if state['power'] > self.upper_bounds:
                self.fault = True
                self.offline_reason = f"Power draw exceeded"
                logging.warning(f"VeSyncAPI ({self.device_name}): Power draw is above upper bounds")
            elif state['power'] < self.lower_bounds:
                self.fault = True
                self.offline_reason = f"Insufficient power draw"
                logging.warning(f"VeSyncAPI ({self.device_name}): Power draw is below lower bounds")
            else:
                self.fault = False
        # if self.last_update < datetime.datetime.now() - datetime.timedelta(minutes=1):
        #     self.online = False
        #     self.offline_reason = f"Data Stale"
        #     logging.warning(f"VeSyncAPI ({self.device_name}): Device has not updated in 1 minute")

    def get_info(self):
        if len(self.device.details) > 1:
            # Check if the data is different from the last time we got it
            self.cached_details = self.device.details
            self.online = True
            details = self.device.details
            details.update({"connection": "online"})
            if self.device.update_energy_ts is not None:
                self.last_update = datetime.datetime.fromtimestamp(self.device.update_energy_ts)

            details.update({"conn_status": self.device.connection_status})

            return details
        else:
            self.online = False
            return {"active_time": 0, "energy": 0, "power": 0, "voltage": 0, "connection": "offline",
                    "conn_status": self.device.connection_status}

    def __str__(self):
        return f"{self.device_name}: {self.get_info()}"

    def __repr__(self):
        return self.__str__()

    def power(self):
        return self.get_info()["power"]

    def voltage(self):
        return self.get_info()["voltage"]

    def energy(self):
        return self.get_info()["energy"]

    def active_time(self):
        return self.get_info()["active_time"]
