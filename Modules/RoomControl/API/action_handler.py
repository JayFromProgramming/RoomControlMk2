import traceback
import typing

from Modules.RoomControl.API.datagrams import APIMessageRX, APIMessageTX
from Modules.RoomControl.AbstractSmartDevices import AbstractRGB, AbstractToggleDevice

import logging

from Modules.RoomControl.LightController import LightController

logging = logging.getLogger(__name__)


def process_device_command(device: typing.Union[AbstractRGB, AbstractToggleDevice], message: APIMessageRX) -> APIMessageTX:
    preformed_actions = []
    try:
        if device is None:
            raise ValueError("Device not found")
        elif isinstance(device, AbstractRGB):
            if hasattr(message, "color"):
                device.set_color(message.color)
                preformed_actions.append(f"set_color to {message.color}")
            if hasattr(message, "brightness"):
                device.set_brightness(message.brightness)
                preformed_actions.append(f"set_brightness to {message.brightness}")
            if hasattr(message, "white"):
                device.set_white(message.white)
                preformed_actions.append(f"set_white to {message.white}")
            if hasattr(message, "on"):
                device.set_on(message.on)
                preformed_actions.append(f"set_on to {message.on}")
            if hasattr(message, "auto"):
                device.set_auto(message.auto, "api")
                preformed_actions.append(f"set_auto to {message.auto}")
        elif isinstance(device, AbstractToggleDevice) or isinstance(device, LightController):
            if hasattr(message, "on"):
                device.set_on(message.on)
                preformed_actions.append(f"set_on to {message.on}")
        else:
            raise TypeError(f"Unknown device type {type(device)}")
    except Exception as e:
        logging.error(f"Error processing device command: {e}")
        return APIMessageTX(
            success=False,
            error=f"Error: {e}\n{traceback.format_exc()}"
        )
    else:
        logging.info(f"Device {device} preformed actions: {preformed_actions}")
        return APIMessageTX(
            success=True,
            preformed_actions=preformed_actions
        )
