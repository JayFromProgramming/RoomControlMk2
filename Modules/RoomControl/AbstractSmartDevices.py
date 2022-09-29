import functools
import threading
from threading import Thread


def background(func):
    """Decorator to automatically launch a function in a thread"""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):  # replaces original function...
        # ...and launches the original in a thread
        thread = Thread(target=func, args=args, kwargs=kwargs, daemon=True)
        thread.start()
        return thread

    return wrapper


class AbstractRGB:

    def __init__(self, device_id, database=None):
        self.online = None
        self.device_id = device_id
        self.is_auto = False
        self.auto_mode = "Unknown"
        self.database = database
        self.offline_reason = "Unknown"

        if database is not None:
            cursor = database.cursor()
            # Check if device is in database
            if cursor.execute("SELECT * FROM auto_lights WHERE device_id = ?", (device_id,)).fetchone() is None:
                cursor.execute("INSERT INTO auto_lights VALUES (?, ?, ?)", (device_id, False, "Unknown"))
                database.lock.acquire()
                database.commit()
                database.lock.release()

    def set_auto(self, auto: bool, mode: str):
        self.is_auto = auto
        self.auto_mode = mode
        cursor = self.database.cursor()
        cursor.execute(
            "UPDATE auto_lights SET device_id = ?, is_auto = ? WHERE current_mode = ?",
            (auto, mode, self.device_id))
        self.database.commit()

    def get_type(self):
        return "abstract_rgb"

    def name(self):
        raise "AbstractRGB"

    def set_color(self, color: tuple):
        raise NotImplementedError

    def get_color(self) -> list:
        return [0, 0, 0]

    @property
    def color(self) -> list:
        return self.get_color()

    @color.setter
    def color(self, color: tuple):
        self.set_color(color)

    def set_brightness(self, brightness: int):
        raise NotImplementedError

    def get_brightness(self) -> int:
        return 0

    @property
    def brightness(self) -> int:
        return self.get_brightness()

    @brightness.setter
    def brightness(self, brightness: int):
        self.set_brightness(brightness)

    def set_on(self, on: bool):
        raise NotImplementedError

    def get_on(self) -> bool:
        raise NotImplementedError

    @property
    def on(self) -> bool:
        return self.get_on()

    @on.setter
    def on(self, on: bool):
        self.set_on(on)

    def set_white(self, white: int):
        raise NotImplementedError

    def get_white(self):
        return False

    @property
    def white(self):
        return self.get_white()

    @white.setter
    def white(self, white: int):
        self.set_white(white)

    def get_state(self):
        return self.get_status() if self.online else {
            "on": False,
            "brightness": 0,
            "color": [
                0,
                0,
                0
            ],
            "white": 0,
            "cold_white": 0,
            "white_enabled": False,
            "mode": "unknown"
        }

    def get_health(self) -> dict:
        return {
            "online": self.online,
            "reason": "online" if self.online else self.offline_reason
        }

    def get_info(self) -> dict:
        return {}

    def get_status(self):
        return {}

    """
    :return: Dict of what the auto mode the device is in
    """

    def auto_state(self) -> dict:
        return {
            "is_auto": self.is_auto,
            "auto_mode": self.auto_mode
        }


class AbstractToggleDevice:

    def __init__(self):
        self.online = None
        self.fault = None
        self.offline_reason = "Unknown"
        self._auto = False

    def get_type(self):
        return "abstract_toggle_device"

    def name(self):
        raise "AbstractToggleDevice"

    def is_on(self):
        raise NotImplementedError

    @property
    def on(self):
        return self.is_on()

    @on.setter
    def on(self, on: bool):
        self.set_on(on)

    def get_state(self):
        return {
            "on": self.is_on()
        }

    def set_on(self, on: bool):
        raise NotImplementedError

    def get_info(self) -> dict:
        return {

        }

    def get_status(self):
        return {}

    def get_health(self):
        return {
            "online": self.online,
            "fault": self.fault,
            "reason": "online" if self.online and not self.fault else self.offline_reason
        }

    @property
    def auto(self):
        return self._auto

    @auto.setter
    def auto(self, auto: bool):
        self._auto = auto

    def auto_state(self):
        return {
            "is_auto": self._auto,
            "auto_mode": None,
        }
