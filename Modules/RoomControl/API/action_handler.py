import traceback
import typing

from Modules.RoomControl.API.datagrams import APIMessageRX, APIMessageTX
from Modules.RoomControl.AbstractSmartDevices import AbstractRGB, AbstractToggleDevice

from loguru import logger as logging

from Modules.RoomControl.EnvironmentController import EnvironmentController


def process_device_command(device:
    typing.Union[AbstractRGB, AbstractToggleDevice, EnvironmentController], message: APIMessageRX) -> tuple[APIMessageTX, bool] | APIMessageTX:
    preformed_actions = []
    try:
        if device is None:
            raise ValueError(f"Device ({device}) not found")
        else:  # Device found
            # if device.is_satellite:

            # print(message.__dict__)
            for key, value in message.__dict__.items():  # Loop through all attributes in the message
                if hasattr(device, key):  # Check the device has an attribute with the same name
                    if value == "True":
                        value = True
                    elif value == "False":
                        value = False
                    setattr(device, key, value)
                    preformed_actions.append(f"set_{key} to {value}")
                else:  # If the device doesn't have an attribute with the same name
                    logging.warning(f"Device {device} has no attribute called {key}")
    except Exception as e:
        logging.error(f"Error processing device command: {e}")
        logging.exception(e)
        return (APIMessageTX(
            success=False,
            error=f"Error: {e}\n{traceback.format_exc()}"
        ), False)
    else:
        logging.info(f"Device {device} preformed actions: {preformed_actions}")
        return (APIMessageTX(
            success=True,
            preformed_actions=preformed_actions
        ), True)
