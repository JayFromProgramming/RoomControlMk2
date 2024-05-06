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
        return
        self.database = room_controller.database

        secrets = self.database.get_table("secrets")
        username = secrets.get_row(secret_name="leviton_username")["secret_value"]
        password = secrets.get_row(secret_name="leviton_password")["secret_value"]
        self.session = DecoraWiFiSession()
        self.session.login(username, password)
        perms = self.session.user.get_residential_permissions()
        for permission in perms:
            acct = residential_account.ResidentialAccount(self.session, permission.residentialAccountId)
            residences = acct.get_residences()
            for residence in residences:
                switches = residence.get_iot_switches()
                for switch in switches:
                    print(switch)

