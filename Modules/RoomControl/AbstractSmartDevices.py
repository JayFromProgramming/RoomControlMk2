import functools
import threading
import time

from loguru import logger as logging


class AbstractRGB:

    def __init__(self):
        self.online = None
        self.is_auto = False
        self.fading = False
        self.fade_thread = None
        self.auto_mode = "Unknown"
        self.offline_reason = "Unknown"

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
        self.fading = False
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
        self.fading = False
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
        :param target: [red, green, blue, warm_white] if warm_white is not null color is ignored
        :param fade_time: The time in seconds that the fade should take
        :return: No return
        """
        try:
            start_color, start_white = self.get_color(), self.get_white() if self.on else 0
            end_color, end_white = target, target[3] if len(target) == 4 else None
            # Calculate how many steps will be needed to take to get to the end color
            color_diff, white_diff = [end_color[i] - start_color[i] for i in range(3)], end_white - start_white
            step_count = max([max([abs(diff) for diff in color_diff]), abs(white_diff)])
            # print(f"Step count: {step_count}, color_diff: {start_color} -> {end_color} = {color_diff}, "
            #       f"white_diff: {start_white} -> {end_white} = {white_diff}")
            if step_count == 0:
                return
            step_time = fade_time / step_count
            for i in range(step_count):
                if not self.fading:
                    logging.info("Fade aborted")
                    return
                if white_diff == 0:
                    color = [start_color[j] + (color_diff[j] / step_count) * i for j in range(3)]
                    color = [int(color[j]) for j in range(3)]
                    self.set_color(tuple(color))
                else:
                    white = start_white + (white_diff / step_count) * i
                    self.set_white(int(white))
                time.sleep(step_time)
            self.fading = False
            logging.info("Fade complete")
        except Exception as e:
            logging.error(f"Error fading: {e}")
            logging.exception(e)

    def _fade(self, args: dict):
        target = args.get("target")
        fade_time = args.get("time")
        if self.fading is True:
            self.fading = False
            self.fade_thread.join()
        self.fading = True
        self.fade_thread = threading.Thread(target=functools.partial(self._fade_process, target, fade_time))
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
