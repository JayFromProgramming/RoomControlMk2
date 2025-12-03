import functools
import random
import threading
import time

from loguru import logger as logging


class AbstractRGB:

    def __init__(self):
        self.online = None
        self.is_auto = False
        self.fading = False
        self.fade_thread = None  # type: threading.Thread | None
        self.auto_mode = "Unknown"
        self.offline_reason = "Unknown"

        self._fade_lock = threading.Lock()
        self._fade_cancel_event = threading.Event()

    def set_auto(self, auto: bool, mode: str):
        self.is_auto = auto
        self.auto_mode = mode

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
        if color is None:
            return
        with self._fade_lock:
            if self.fading:
                self.fading = False
                self._fade_cancel_event.set()
                if self.fade_thread is not None:
                    self.fade_thread.join()
        self.set_color(color)

    def set_brightness(self, brightness: int):
        raise NotImplementedError

    def get_brightness(self) -> int:
        raise NotImplementedError

    @property
    def brightness(self) -> int:
        return self.get_brightness()

    @brightness.setter
    def brightness(self, brightness: int):
        if brightness < 0 or brightness > 255:
            raise ValueError("Brightness must be between 0 and 255")
        if brightness is None:
            return
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
        with self._fade_lock:
            if self.fading:
                self.fading = False
                self._fade_cancel_event.set()
                if self.fade_thread is not None:
                    self.fade_thread.join()
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

    def _fade_process(self, target: tuple, fade_time: int):
        """
        Optimized fade loop:
        - Uses monotonic clock for timing.
        - Computes step_count based on largest channel change (or white).
        - Uses float accumulation and rounds only when calling device setters.
        - Checks a cancel event to abort promptly.
        """
        try:
            start_monotonic = time.monotonic()
            start_color = self.get_color() if self.on else [0, 0, 0]
            start_white = self.get_white() if self.on else 0

            # Normalize target
            if target is None:
                logging.info("Fade target is None, aborting")
                return
            end_color = list(target[:3])
            end_white = target[3] if len(target) == 4 else None

            color_diff = [end_color[i] - start_color[i] for i in range(3)]
            white_diff = (end_white - start_white) if end_white is not None else 0

            # Number of steps is the maximum absolute change to ensure smooth increments
            step_count = max([abs(d) for d in color_diff] + ([abs(white_diff)] if end_white is not None else [0])) or 0
            if step_count == 0 or fade_time <= 0:
                # Direct set if no stepping needed or invalid time
                if end_white is None:
                    self.set_color(tuple(int(round(c)) for c in end_color))
                else:
                    self.set_white(int(round(end_white)))
                return

            step_time = fade_time / step_count

            # Add a slight start delay which is some random fraction of step_time to avoid all devices updating simultaneously
            initial_delay = step_time * random.uniform(0, 1)
            time.sleep(initial_delay)
            start_monotonic += initial_delay  # Adjust start time to account for initial delay

            logging.info(f"Fading over {fade_time}s in {step_count} steps, step time {step_time:.4f}s")

            # Use floats for internal progression to avoid cumulative rounding error
            for step in range(1, int(step_count) + 1):
                if self._fade_cancel_event.is_set():
                    logging.info("Fade cancelled")
                    return

                progress = step / step_count

                if end_white is None:
                    next_color = [
                        start_color[i] + color_diff[i] * progress
                        for i in range(3)
                    ]
                    self.set_color(tuple(int(round(c)) for c in next_color))
                else:
                    next_white = start_white + white_diff * progress
                    self.set_white(int(round(next_white)))

                # Sleep until the next target time (use absolute scheduling to avoid drift)
                target_time = start_monotonic + step * step_time
                now = time.monotonic()
                to_sleep = target_time - now
                if to_sleep > 0:
                    time.sleep(to_sleep)

            logging.info("Fade complete")
        except Exception as e:
            logging.error(f"Error fading: {e}")
            logging.exception(e)
        finally:
            # Clear flags and event regardless of exit mode
            self.fading = False
            self._fade_cancel_event.clear()
            self.fade_thread = None

    def _fade(self, args: dict):
        target = args.get("target")
        fade_time = args.get("time")

        with self._fade_lock:
            if self.fading:
                logging.info("Cancelling previous fade")
                self.fading = False
                self._fade_cancel_event.set()
                if self.fade_thread is not None:
                    self.fade_thread.join(timeout=1)

            logging.info(f"Starting fade to {target} over {fade_time} seconds")
            self.fading = True
            self._fade_cancel_event.clear()
            self.fade_thread = threading.Thread(target=self._fade_process, args=(target, fade_time), daemon=True)
            self.fade_thread.start()

    @property
    def fade(self):
        return LookupError

    @fade.setter
    def fade(self, args: dict):
        self._fade(args)

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
            "fade_active": False,
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

    def auto_state(self) -> dict:
        """
            :return: Dict of what the auto mode the device is in
        """
        return {
            "is_auto": self.is_auto,
            "auto_mode": self.auto_mode
        }


class AbstractToggleDevice:

    def __init__(self):
        self.online = None
        self.fault = None
        self.delaying = False  # This is the toggle device equivalent of fading
        self.delay_thread = None
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
        if self.delaying is True:
            logging.info("Cancelling previous delay")
            self.delaying = False
            if self.delay_thread is not None:
                self.delay_thread.cancel()
        self.set_on(on)

    def get_state(self):
        return {
            "on": self.is_on()
        }

    def set_on(self, on: bool):
        raise NotImplementedError

    def _delay_action(self, state):
        self.delaying = False
        self.set_on(state)

    def _delay(self, end_state: bool, delay_time: int):
        logging.info(f"Delaying action for {delay_time} seconds")
        if self.delaying is True:
            logging.info("Cancelling previous delay")
            self.delay_thread.cancel()
            self.delaying = False
        self.delay_thread = threading.Timer(delay_time, self._delay_action, args=(end_state,))
        self.delay_thread.start()
        self.delaying = True

    @property
    def delay(self):
        return LookupError

    @delay.setter
    def delay(self, args: dict):
        self._delay(args.get("state"), args.get("time"))

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
        if not isinstance(auto, bool):
            raise ValueError("Auto must be a boolean")
        self._auto = auto

    def auto_state(self):
        return {
            "is_auto": self._auto,
            "auto_mode": None,
        }
