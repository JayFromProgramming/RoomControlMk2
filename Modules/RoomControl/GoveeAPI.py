import random
import time

from Modules.RoomControl import background
from Modules.RoomControl.AbstractSmartDevices import AbstractToggleDevice
from Modules.RoomModule import RoomModule
from loguru import logger as logging
import requests

from Modules.RoomObject import RoomObject

api_endpoint = "https://openapi.api.govee.com"


class GoveeAPI(RoomModule):

    def __init__(self, room_controller):
        super().__init__(room_controller)
        self.database = room_controller.database

        secrets = self.database.get_table("secrets")
        self.api_key = secrets.get_row(secret_name="govee_key")["secret_value"]

        devices_payload = self.request_devices()
        self.devices = []
        for device in devices_payload["data"]:
            logging.info(f"Creating device {device['deviceName']} [{device['device']}]")
            self.devices.append(GoveeDevice(room_controller, self.api_key, device["sku"], device["device"]))

    def request_devices(self):
        url = f"{api_endpoint}/router/api/v1/user/devices"
        headers = {
            "Govee-API-Key": self.api_key
        }
        response = requests.get(url, headers=headers)
        return response.json()

    def get_device(self, device_id):
        for device in self.devices:
            if device.device_id == device_id:
                return device


class GoveeDevice:

    def __init__(self, room_controller, api_key, device_sku, device_id):
        self.room_controller = room_controller
        self.device_id = device_id
        self.device_sku = device_sku
        self.api_key = api_key
        # Device info variables
        self.online = None
        self.plug_states = None
        self.periodic_refresh()

    @background
    def periodic_refresh(self):
        while True:
            self._get_device_info()
            logging.info(f"Device {self.device_id} is {'online' if self.online else 'offline'}")
            time.sleep(60)

    @background
    def _get_device_info(self):
        url = f"{api_endpoint}/router/api/v1/device/state"
        headers = {
            "content-type": "application/json",
            "Govee-API-Key": self.api_key
        }
        params = {
            "requestId": random.randint(0, 100000),
            "payload": {
                "sku": self.device_sku,
                "device": self.device_id
            }
        }
        response = requests.post(url, headers=headers, json=params)
        data = response.json()["payload"]
        capabilities = data["capabilities"]
        for capability in capabilities:
            match capability["type"]:
                case 'devices.capabilities.online':
                    self.online = capability["state"]["value"]
                case 'devices.capabilities.on_off':
                    self.plug_states = capability["state"]["value"]

    # def send_command(self, on: bool):
    #     url = f"{api_endpoint}/router/api/v1/device/control"
    #     headers = {
    #         "content-type": "application/json",
    #         "Govee-API-Key": self.api_key
    #     }
    #     params = {
    #         "requestId": random.randint(0, 100000),
    #         "payload": {
    #             "sku": self.device_sku,
    #             "device": self.device_id,
    #             "capability": {
    #                 "type": "devices.capabilities.on_off",
    #                 "instance": "powerSwitch",
    #                 "value": 1 if on else 0
    #             }
    #         }
    #     }
    #     response = requests.post(url, headers=headers, json=params)
    #     logging.info(f"Sent command to device {self.device_id} to turn {'on' if on else 'off'}")



