import datetime
import enum
import time

from midea_beautiful import find_appliances, LanDevice

from Modules.RoomControl.CoreModules.AbstractSmartDevices import AbstractToggleDevice
from Modules.RoomControl.CoreModules.Decorators import background

from loguru import logger as logging

from Modules.RoomModule import RoomModule
from Modules.RoomObject import RoomObject

def all_addresses_in_subnet(subnet: str) -> list[str]:
    import ipaddress
    return [str(ip) for ip in ipaddress.IPv4Network(subnet).hosts()]

class MideaAPI(RoomModule):

    def __init__(self, room_controller):
        super().__init__(room_controller)
        self.devices = []
        self.database = room_controller.database
        self.find_appliances()

    @background
    def find_appliances(self):
        logging.info("MideaAPI: Finding appliances...")
        secretes_table = self.database.get_table("secrets")
        email = secretes_table.get_row(secret_name='MideaUsername')
        password = secretes_table.get_row(secret_name='MideaPassword')

        all_addresses = all_addresses_in_subnet("192.168.1.0/24")
        logging.info(f"MideaAPI: Scanning for appliances in subnet with addresses: {all_addresses[0]} - {all_addresses[-1]} (len={len(all_addresses)})")

        appliances = find_appliances(
            account=email['secret_value'],
            password=password['secret_value'],
            addresses=all_addresses,  # Look for all appliances in the subnet due to broadcast issues
            timeout=0.1
        )
        logging.info(f"MideaAPI: Found {len(appliances)} appliances.")
        for appliance in appliances:
            self.create_device(appliance)

    def create_device(self, appliance_object):
        device = MideaDevice(appliance_object, self.room_controller)
        self.devices.append(device)
        return device

class MideaDevice(RoomObject):

    is_promise = False
    supported_actions = ["on", "target_value", "mode", "fan_speed", "fan_auto"]

    class Modes(enum.IntEnum):
        UNKNOWN = 0
        AUTO = 1
        COOL = 2
        DRY = 3
        FAN = 5
        HEAT = 4

    @staticmethod
    def celsius_to_fahrenheit(celsius):
        return round(celsius * 9 / 5 + 32, 1)

    @staticmethod
    def fahrenheit_to_celsius(fahrenheit):
        return (fahrenheit - 32) * 5 / 9

    def __init__(self, appliance_object: LanDevice, room_controller):
        super().__init__(appliance_object.mac, 'MideaDevice')
        logging.info(f"Creating MideaDevice {appliance_object.model}: {appliance_object.mac}@{appliance_object.address}")
        self.appliance = appliance_object
        self.address = appliance_object.address
        self.last_updated = datetime.datetime.now()

        self.refresh_loop()
        room_controller.attach_object(self)

    @background
    def refresh_loop(self):
        while True:
            try:
                self.appliance.refresh()
                self.last_updated = datetime.datetime.now()
            except Exception as e:
                logging.error(f"Error refreshing Midea appliance {self.object_name}: {e}")
                logging.exception(e)
            time.sleep(1)

    def get_state(self):
        return {
            "on": self.appliance.state.running,
            "target_temperature": self.celsius_to_fahrenheit(self.appliance.state.target_temperature),
            "indoor_temperature": self.celsius_to_fahrenheit(self.appliance.state.indoor_temperature),
            "outdoor_temperature": self.celsius_to_fahrenheit(self.appliance.state.outdoor_temperature),
            "mode": self.Modes(self.appliance.state.mode).name,
            "mode_int": self.appliance.state.mode,
            "fan_speed": self.appliance.state.fan_speed,
            "fan_auto": True if self.appliance.state.fan_speed == 102 else False,
            "turbo": self.appliance.state.turbo,
            "turbo_fan": self.appliance.state.turbo_fan,
            "eco_mode": self.appliance.state.eco_mode,
            "frost_protection": self.appliance.state.frost_protect,
            "vertical_swing": self.appliance.state.vertical_swing,
            "horizontal_swing": self.appliance.state.horizontal_swing,
        }

    def get_info(self):
        return {
            "model": self.appliance.model,
            "address": self.appliance.address,
            "mac": self.appliance.mac,
            "ssid_name": self.appliance.ssid,
            "firmware_version": self.appliance.firmware_version,
            "last_updated": self.last_updated.isoformat(),
        }

    def get_health(self):
        return {
            # "last_updated": self.appliance.last_updated,
            "online": self.appliance.online,
            "fault": self.appliance.state.error_code != 0,
            "reason": self.appliance.last_error,
        }

    def get_type(self):
        return "MideaDevice"

    def set_on(self, on: bool):
        try:
            if on:
                self.appliance.set_state(running=True)
            else:
                self.appliance.set_state(running=False)
        except Exception as e:
            logging.error(f"Error setting Midea appliance {self.object_name} on={on}: {e}")
            logging.exception(e)

    @property
    def on(self):
        return self.appliance.state.running

    @on.setter
    def on(self, value):
        self.set_on(value)

    @property
    def target_value(self):
        return self.celsius_to_fahrenheit(self.appliance.state.target_temperature)

    @target_value.setter
    def target_value(self, value):
        celsius = self.fahrenheit_to_celsius(value)
        try:
            self.appliance.set_state(target_temperature=celsius)
            logging.info(f"Set Midea appliance {self.object_name} target_value={value} (celsius={celsius})")
        except Exception as e:
            logging.error(f"Error setting Midea appliance {self.object_name} target_value={value} (celsius={celsius}): {e}")
            logging.exception(e)

    @property
    def mode(self):
        return self.Modes(self.appliance.state.mode).name

    @mode.setter
    def mode(self, value):
        try:
            mode_value = self.Modes[value.upper()].value if isinstance(value, str) else int(value)
            self.appliance.set_state(mode=mode_value)
        except Exception as e:
            logging.error(f"Error setting Midea appliance {self.object_name} mode={value}: {e}")
            logging.exception(e)

    @property
    def fan_speed(self):
        return self.appliance.state.fan_speed

    @fan_speed.setter
    def fan_speed(self, value):
        try:
            self.appliance.set_state(fan_speed=int(value))
        except Exception as e:
            logging.error(f"Error setting Midea appliance {self.object_name} fan_speed={value}: {e}")
            logging.exception(e)

    @property
    def turbo(self):
        return self.appliance.state.turbo

    @turbo.setter
    def turbo(self, value):
        try:
            self.appliance.set_state(turbo=bool(value))
            self.appliance.set_state(turbo_fan=bool(value))
        except Exception as e:
            logging.error(f"Error setting Midea appliance {self.object_name} turbo={value}: {e}")
            logging.exception(e)

    @property
    def eco(self):
        return self.appliance.state.eco_mode

    @eco.setter
    def eco(self, value):
        try:
            self.appliance.set_state(eco_mode=bool(value))
        except Exception as e:
            logging.error(f"Error setting Midea appliance {self.object_name} eco_mode={value}: {e}")
            logging.exception(e)





