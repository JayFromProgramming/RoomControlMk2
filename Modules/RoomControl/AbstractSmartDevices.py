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
        self.device_id = device_id
        self.is_auto = False
        self.auto_mode = "Unknown"
        self.database = database

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
        self.database.cursor.execute(
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

    def set_brightness(self, brightness: int):
        raise NotImplementedError

    def get_brightness(self) -> int:
        return 0

    def set_on(self, on: bool):
        raise NotImplementedError

    def set_white(self, white: int):
        raise NotImplementedError

    def get_white(self):
        return False

    def get_state(self):
        return self.get_status()

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

    def get_type(self):
        return "abstract_toggle_device"

    def name(self):
        raise "AbstractToggleDevice"

    def set_on(self, on: bool):
        raise NotImplementedError

    def get_state(self) -> bool:
        raise False

    def get_status(self):
        raise {}

    def auto_state(self):
        return {
            "is_auto": False,
            "auto_mode": None,
        }
