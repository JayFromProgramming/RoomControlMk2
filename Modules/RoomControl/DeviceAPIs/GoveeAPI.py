import random
import time

from kasa.cli.device import device

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
        self.init_database()
        secrets = self.database.get_table("secrets")
        try:
            self.api_key = secrets.get_row(secret_name="govee_key")["secret_value"]
        except Exception as e:
            logging.error(f"Govee API key not found in secrets table or error: {e}")
            return
        self.devices = []
        devices_payload = self.request_devices()
        for device in devices_payload["data"]:
            logging.info(f"Creating device {device['deviceName']} [{device['device']}]")
            self.devices.append(GoveeDevice(room_controller, self.api_key, device["sku"], device["device"]))

    def init_database(self):
        self.database.create_table("govee_devices", {"device_id": "TEXT", "device_sku": "TEXT",
                                                     "plug_index": "INTEGER", "state": "BOOLEAN"},
                                        primary_keys=["device_id", "plug_index"])

    def request_devices(self):
        url = f"{api_endpoint}/router/api/v1/user/devices"
        headers = {
            "Govee-API-Key": self.api_key
        }
        response = requests.get(url, headers=headers)
        return response.json()

    def get_device(self, device_id):
        try:
            for device in self.devices:
                if device.device_id == device_id:
                    return device
        except Exception as e:
            logging.error(f"Error getting device {device_id}: {e}")
            pass


class GoveeDevice:

    def __init__(self, room_controller, api_key, device_sku, device_id):
        self.room_controller = room_controller
        self.device_id = device_id
        self.device_sku = device_sku
        self.api_key = api_key
        # Device info variables
        self.online = None
        self.offline_reason = "Unknown"
        self.both_switches_off = None
        self.initialized = False
        self.child_objects = [GoveeOutlet(room_controller, self, device_id, 0),
                              GoveeOutlet(room_controller, self, device_id, 1)]
        self.periodic_refresh()
        self.reset_logic()

    @background
    def periodic_refresh(self):
        while True:
            try:
                self._get_device_info()
            except Exception as e:
                self.online = False
                self.offline_reason = f"API Error: {e}"
                logging.error(f"Error refreshing Govee device {self.device_id}: {e}")
            finally:
                time.sleep(30)

    def reset_logic(self):
        if self.child_objects[0].state is False and self.child_objects[1].state is False:
            # If both outlets are supposed to be off, we can command the device to turn off all switches
            self._reset_switch(False)
        elif self.child_objects[0].state is True and self.child_objects[1].state is True:
            # If at least one outlet is on, we can command the device to turn on all switches
            self._reset_switch(True)
        elif self.child_objects[0].state is False and self.child_objects[1].state is True:
            # If the first outlet is off and the second is on, we can command the device to turn on the first switch
            self._reset_switch(False)
            self._toggle_switch(0)
        elif self.child_objects[0].state is True and self.child_objects[1].state is False:
            # If the first outlet is on and the second is off, we can command the device to turn on the second switch
            self._reset_switch(False)
            self._toggle_switch(1)
        else:
            logging.error(f"Unexpected state for Govee device {self.device_id}: "
                          f"{self.child_objects[0].state}, {self.child_objects[1].state}")


    def set_outlet(self, index, state: bool):
        # If setting this outlet on will turn both switches on, we can just send an all on command
        other_state = self.child_objects[0 if index == 1 else 1].state
        if state is True and other_state is True:
            self._reset_switch(False)
        elif state is True and other_state is False:
            self._reset_switch(True)
        else:
            if state == self.child_objects[index].state:
                return
        if self._toggle_switch(index):
            self.child_objects[index].state = state

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
        self.initialized = True
        capabilities = data["capabilities"]
        for capability in capabilities:
            match capability["type"]:
                case 'devices.capabilities.online':
                    self.online = capability["state"]["value"] == 1
                    if not self.online:
                        self.offline_reason = "Govee Device Offline"
                    else:
                        self.offline_reason = "Unknown"
                case 'devices.capabilities.on_off':
                    self.both_switches_off = capability["state"]["value"] == 0


    def _reset_switch(self, state: bool = False):
        url = f"{api_endpoint}/router/api/v1/device/control"
        headers = {
            "content-type": "application/json",
            "Govee-API-Key": self.api_key
        }
        params = {
            "requestId": random.randint(0, 100000),
            "payload": {
                "sku": self.device_sku,
                "device": self.device_id,
                "capability": {
                    "type": "devices.capabilities.on_off",
                    "instance": 'powerSwitch',
                    "value": 1 if state else 0
                }
            }
        }
        response = requests.post(url, headers=headers, json=params)
        if response.status_code == 200:
            logging.info(f"Reset switch for device {self.device_id} to {'on' if state else 'off'}")
            self.child_objects[0].state = state
            self.child_objects[1].state = state
            return True
        else:
            logging.error(f"Failed to reset switch for device {self.device_id}: {response.text}")
            return False

    def _toggle_switch(self, switch: int = 0):
        url = f"{api_endpoint}/router/api/v1/device/control"
        headers = {
            "content-type": "application/json",
            "Govee-API-Key": self.api_key
        }
        params = {
            "requestId": random.randint(0, 100000),
            "payload": {
                "sku": self.device_sku,
                "device": self.device_id,
                "capability": {
                    "type": "devices.capabilities.toggle",
                    "instance": f"socketToggle{switch}",
                    "value": 0 if self.child_objects[switch].state else 1
                }
            }
        }
        response = requests.post(url, headers=headers, json=params)
        if response.status_code == 200:
            logging.info(f"Sent toggle command to device {self.device_id} for switch {switch}")
            return True
        else:
            return False

class GoveeOutlet(RoomObject, AbstractToggleDevice):
    """
    Govee Outlet Device Class
    """
    supported_actions = ["on", "delay"]

    def __init__(self, room_controller, parent_device, device_id: str, plug_index: int = 0):
        super().__init__(f"{device_id}-{plug_index}", "GoveeOutlet")
        self.outlet_id = device_id
        self.plug_index = plug_index
        self.govee_device = parent_device
        self.online = self.govee_device.online
        self.offline_reason = "Unknown"
        self.fault = False
        self.table = room_controller.database.get_table("govee_devices")
        self.initialized = self.govee_device.initialized
        self.state = False  # Default state is off
        self.load_state()
        room_controller.attach_object(self)

    def load_state(self):
        entry = self.table.get_row(device_id=self.outlet_id, plug_index=self.plug_index)
        if entry:
            self.state = True if entry["state"] == 1 else False
            logging.info(f"Loaded state for {self.outlet_id} plug {self.plug_index}: {self.state}")
        else:
            logging.warning(f"No state found for {self.outlet_id} plug {self.plug_index}, defaulting to off")
            self.state = False
            self.save_state()

    def save_state(self):
        self.table.update_or_add(device_id=self.outlet_id, plug_index=self.plug_index, state=self.state)
        logging.info(f"Saved state for {self.outlet_id} plug {self.plug_index}: {self.state}")

    def get_type(self):
        return "GoveeOutlet"

    def is_on(self):
        return self.state

    def set_on(self, on: bool):
        if not self.govee_device.initialized:
            logging.error(f"Govee device {self.device_id} is not initialized")
            return
        self.govee_device.set_outlet(self.plug_index, on)
        self.save_state()


