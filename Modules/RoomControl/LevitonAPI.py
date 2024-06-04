import datetime
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
        self.room_controller = room_controller
        self.session = DecoraWiFiSession()
        self.devices = []
        self.connect()
        self.leviton_periodic_refresh()

    @background
    def connect(self):
        secrets = self.database.get_table("secrets")
        username = secrets.get_row(secret_name="leviton_username")["secret_value"]
        # username = " "
        password = secrets.get_row(secret_name="leviton_password")["secret_value"]
        self.session.login(username, password)
        perms = self.session.user.get_residential_permissions()
        for permission in perms:
            print(permission)
            acct = residential_account.ResidentialAccount(self.session, permission.residentialAccountId)
            residences = acct.get_residences()
            for residence in residences:
                print(residence)
                switches = residence.get_iot_switches()
                for switch in switches:
                    self.devices.append(LevitonDevice(self.room_controller, switch))

    @background
    def leviton_periodic_refresh(self):
        while True:
            for device in self.devices:
                device.refresh_info()
            time.sleep(5)


class LevitonDevice(RoomObject, AbstractToggleDevice):
    is_promise = False
    supported_actions = ["toggleable", "brightness"]

    def __init__(self, room_controller, switch):
        super().__init__(switch.mac, "LevitonDevice")
        self.room_controller = room_controller
        self.switch = switch
        self.mac_address = switch.mac
        timestamp = switch.lastUpdated
        timestamp = timestamp.replace("Z", "+00:00")
        self.last_updated = datetime.datetime.fromisoformat(timestamp)
        self.room_id = switch.residentialRoomId

        self.online = self.switch.connected
        self.local_ip = None
        if self.online:
            self.local_ip = self.switch.localIP
            self.signal_strength = self.switch.rssi
        self.dimmable = self.switch.canSetLevel
        self.min_level = self.switch.minLevel
        self.max_level = self.switch.maxLevel

        logging.info(f"Leviton Device {self.switch.name}[{self.mac_address}]"
                     f" is {'online' if self.online else 'offline'}")
        self.leviton_periodic_refresh()
        self.auto = False
        self.room_controller.attach_object(self)

    def refresh_info(self):
        try:
            self.switch.refresh()
            self.online = self.switch.connected
            self.local_ip = None
            if self.online:
                self.local_ip = self.switch.localIP
        except Exception as e:
            logging.error(f"Failed to refresh Leviton Device {self.switch.name}[{self.mac_address}]: {e}")
            self.online = False

    def get_display_name(self):
        return self.switch.name

    def get_type(self):
        return "LevitonDevice"

    def set_on(self, on: bool):
        self.switch.update_attributes({'power': 'ON' if on else 'OFF'})

    @property
    def brightness(self):
        return self.get_brightness()

    @brightness.setter
    def brightness(self, value: int):
        self.set_brightness(value)

    @background
    def set_brightness(self, brightness: int):
        if not self.dimmable:
            self.set_on(brightness > 0)
        else:
            self.switch.update_attributes({'brightness': str(brightness), 'power': 'ON' if brightness > 0 else 'OFF'})

    def get_brightness(self):
        return self.switch.data['brightness']

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
            "dimmable": self.dimmable,
            "min_level": self.min_level,
            "max_level": self.max_level,
            "signal_strength": self.signal_strength,
            "last_updated": self.last_updated.timestamp()
        }
