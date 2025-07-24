import asyncio
import random
from typing import Optional
from loguru import logger as logging
from Modules.RoomObject import RoomObject


class SatelliteDevice(RoomObject):
    is_promise = False
    is_satellite = True
    """
    Represents a satellite device in the room control system.
    This class is used to manage the satellite device's state and interactions.
    """

    def __init__(self, satellite_handler, device_id: str, device_type: str = "satellite_device"):
        """
        Initialize the satellite device with the room controller and a unique device ID.

        :param satellite_handler: The satellite handler instance managing communication with this device.
        :param device_id: A unique identifier for the satellite device.
        """
        self.device_id = f"{satellite_handler.satellite_id}.{device_id}"
        self.satellite_handler = satellite_handler
        asyncio.create_task(self.heartbeat())
        super().__init__(self.device_id, device_type)
        self.satellite_handler.room_controller.attach_object(self)

    def set_value(self, key, value):
        """
        Set a value for the satellite device and emit an event if the value has changed.
        :param key: The key of the value to set.
        :param value: The value to set.
        """
        if self._values.get(key, None) != value:
            self.emit_event(f"on_{key}_update", value, dont_repeat=True)
        self._values[key] = value

    def get_state(self):
        return self.get_values()

    def get_type(self):
        return self.object_type

    def emit_event(self, event_name, *args, **kwargs):
        """
        Emit an event to all attached callbacks
        :param event_name: The name of the event to emit
        :param args: Any arguments to pass to the callback
        :param kwargs: Any keyword arguments to pass to the callback
        """
        if "dont_repeat" not in kwargs:
            self.satellite_handler.send_uplink(self, event_name, *args, **kwargs)
        # Strip the dont_repeat argument from the kwargs
        kwargs.pop("dont_repeat", None)
        super().emit_event(event_name, *args, **kwargs)

    def get_health(self):
        online = self.satellite_handler.online() and self._health.get("online", False)
        fault = self._health.get("fault", False)
        reason = self._health.get("reason", "") if self.satellite_handler.online() else\
            f"Satellite [{self.satellite_handler.satellite_id}] is offline"
        return {
            "online": online,
            "fault": fault,
            "reason": reason
        }

    async def heartbeat(self):
        logging.info(f"Starting heartbeat for {self.object_name}")
        while True:
            if self.satellite_handler.online():
                # logging.info(f"Sending heartbeat to {self.object_name}")
                self.emit_event("heartbeat")
            variable_delay = 60 + random.randint(0, 30)  # Random delay between 60 and 90 seconds
            await asyncio.sleep(variable_delay)

    @property
    def on(self):
        return self.get_state().get("on", False)

    @on.setter
    def on(self, state):
        if not self.satellite_handler.online():
            logging.warning(f"Cannot set state of {self.object_name} because the satellite is offline")
            return
        if not isinstance(state, bool):
            logging.warning(f"Cannot set state of {self.object_name} to {state} because it is not a boolean")
            return
        # Use the main event loop to set the state not the event loop of the calling method
        self.satellite_handler.send_uplink(self, "set_on", state)
