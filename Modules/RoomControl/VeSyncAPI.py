import datetime
import typing

from pyvesync import VeSync
import asyncio
from threading import Thread

import ConcurrentDatabase
from Modules.RoomControl.AbstractSmartDevices import AbstractToggleDevice
from Modules.RoomControl.Decorators import background

from loguru import logger as logging

from Modules.RoomModule import RoomModule
from Modules.RoomObject import RoomObject


class VeSyncAPI(RoomModule):

    def __init__(self, room_controller):
        super().__init__(room_controller)

        self.database = room_controller.database
        secretes_table = self.database.get_table("secrets")
        email = secretes_table.get_row(secret_name='VesyncUsername')
        password = secretes_table.get_row(secret_name='VesyncPassword')
        self.manager = VeSync(email['secret_value'], password['secret_value'], time_zone='America/New_York')

        try:
            self.manager.login()
        except Exception as e:
            logging.error(f"VeSyncAPI: Error logging in: {e}")
            return

        self.manager.update()  # Populate the devices list

        self.devices = []
        for device in self.manager.outlets:
            self.devices.append(VeSyncPlug(device, self.room_controller))

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


class VeSyncPlug(RoomObject, AbstractToggleDevice):

    is_promise = False
    supported_actions = ["toggleable"]

    def __init__(self, device, room_controller):
        super(VeSyncPlug, self).__init__(device.device_name, "VeSyncPlug")

        self.device = device
        self.device_name = device.device_name
        self.cached_details = {}
        self.online = True
        self.fault = False
        self.last_update = datetime.datetime.now()
        self.database = room_controller.database
        self.upper_bounds = None
        self.lower_bounds = None
        self.get_bounds()
        self.room_controller = room_controller
        self.auto = False
        self.room_controller.attach_object(self)

    def get_bounds(self):
        """Gets expected power draw bounds from the DB"""
        device_bounds = self.database.get_table("vesync_device_bounds")
        bounds = device_bounds.get_row(device_name=self.device_name)
        if bounds:
            logging.info(f"VeSyncAPI ({self.device_name}): Bounds found in DB: {bounds}")
            self.upper_bounds = bounds["upper_bound"]
            self.lower_bounds = bounds["lower_bound"]
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
        if self.upper_bounds and self.lower_bounds:
            state = self.get_info()
            if state["active_time"] < 2:  # If the device has been on for less than 2 minutes
                self.fault = False
                return  # Its power draw is probably not accurate
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
        try:
            self.device.get_details()
            self.device.update()
            self.device.update_energy()
        except Exception as e:
            logging.warning(f"VeSyncAPI ({self.device_name}): Error getting device details: {e}")
            self.online = False
            self.offline_reason = f"API Error"
            return self.cached_details
        if len(self.device.details) > 1:
            # Check if the data is different from the last time we got it
            self.cached_details = self.device.details
            self.online = True
            details = self.device.details
            if self.device.update_energy_ts is not None:
                self.last_update = datetime.datetime.fromtimestamp(self.device.update_energy_ts)

            # details.update({"connection": self.device.connection_status})
            # if self.device.connection_status == "offline":
            #     self.online = False
            #     self.offline_reason = f"No Response"
            #     logging.warning(f"VeSyncAPI ({self.device_name}): Device is offline")
            details.update({"connection": "online"})
            return details
        else:
            self.online = False
            return {"active_time": 0, "energy": 0, "power": 0, "voltage": 0,
                    "connection": "offline"}

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
