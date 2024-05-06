import random
import time

from Modules.RoomControl import background
from Modules.RoomControl.AbstractSmartDevices import AbstractToggleDevice
from Modules.RoomModule import RoomModule
from loguru import logger as logging

from Modules.RoomObject import RoomObject
from decora_wifi import DecoraWiFiSession
from decora_wifi.models import residential_account


class LevitonAPI(RoomModule):

    def __init__(self, room_controller):
        super().__init__(room_controller)
        self.database = room_controller.database

        secrets = self.database.get_table("secrets")
        username = secrets.get_row(secret_name="leviton_username")["secret_value"]
        password = secrets.get_row(secret_name="leviton_password")["secret_value"]
        self.session = DecoraWiFiSession()
        self.session.login(username, password)
        self.devices = []
        print(self.session.user)
        perms = self.session.user.get_residential_permissions()
        for permission in perms:
            print(permission)
            acct = residential_account.ResidentialAccount(self.session, permission.residentialAccountId)
            residences = acct.get_residences()
            for residence in residences:
                print(residence)
                switches = residence.get_iot_switches()
                for switch in switches:
                    self.devices.append(LevitonDevice(room_controller, switch))


class LevitonDevice(RoomObject, AbstractToggleDevice):

    def __init__(self, room_controller, switch):
        super().__init__(switch.mac, "LevitonDevice")
        self.room_controller = room_controller
        self.switch = switch
        self.mac_address = switch.mac

        self.online = self.switch.connected
        self.local_ip = None
        if self.online:
            self.local_ip = self.switch.localIP
        self.dimmable = self.switch.canSetLevel

        logging.info(f"Leviton Device {self.switch.name}[{self.mac_address}]"
                     f" is {'online' if self.online else 'offline'}")
        self.periodic_refresh()
        self.room_controller.attach_object(self)

    @background
    def periodic_refresh(self):
        while True:
            self.switch.refresh()
            self.online = self.switch.connected
            self.local_ip = None
            if self.online:
                self.local_ip = self.switch.localIP
            time.sleep(5)

    def get_display_name(self):
        return self.switch.name

    def get_type(self):
        return "LevitonDevice"

    def set_on(self, on: bool):
        self.switch.update_attributes({'power': 'ON' if on else 'OFF'})

    def set_brightness(self, brightness: int):
        self.switch.update_attributes({'presetLevel': brightness})

    def get_brightness(self):
        return self.switch.data['presetLevel']

    def is_on(self):
        return self.switch.power == 'ON'

    def get_state(self):
        return {
            "on": self.is_on(),
            "brightness": self.get_brightness() if self.dimmable else None
        }

    def get_health(self):
        return {
            "online": self.online,
            "fault": False,
            "reason": "online" if self.online else "Switch Unresponsive",
        }

    def get_info(self):
        return {
            "local_ip": self.local_ip,
            "dimmable": self.dimmable
        }
