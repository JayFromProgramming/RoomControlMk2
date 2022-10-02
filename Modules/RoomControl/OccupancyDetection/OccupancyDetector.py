from Modules.RoomControl.OccupancyDetection.BluetoothOccupancy import BluetoothDetector
import logging

logging = logging.getLogger(__name__)

try:
    import RPi.GPIO as GPIO
except ImportError:
    GPIO = None
    logging.warning("RPi.GPIO not found, GPIO will not be available")


class OccupancyDetector:

    def __init__(self, database):
        self.database = database
        self.sources = {}

        self.blue_stalker = BluetoothDetector(self.database, connect_on_queue=True if GPIO else False)
        if GPIO:
            GPIO.setmode(GPIO.BOARD)
        self.motion_pin = PinWatcher("motion", 11, self.motion_detected, bouncetime=200)
        self.door_pin = PinWatcher("door", 15, self.motion_detected, bouncetime=200)

        self.sources = {
            "bluetooth": self.blue_stalker,
            "motion": self.motion_pin,
            "door": self.door_pin
        }

    def motion_detected(self, pin):
        logging.info("Motion Detected on pin {}".format(pin))
        self.blue_stalker.should_scan()

    def is_here(self, device):
        return self.blue_stalker.is_here(device)

    def get_name(self, device):
        return self.blue_stalker.get_name(device)

    def get_all_devices(self):
        return self.sources.values()

    def get_device(self, device_id):
        for device in self.sources.values():
            if device.name() == device_id:
                return device


class PinWatcher:

    def __init__(self, name, pin, callback: callable, edge=None, bouncetime=200, normally_open=False):
        self.online = True
        self.fault = False
        self.fault_message = ""
        self.pin = pin  # Pin number
        self.state = None  # None = Unknown, True = On, False = Off
        self._name = name  # Name of the device
        self.enabled = True  # Is the device enabled for detection

        self.callback = callback
        self.edge = None
        self.bouncetime = bouncetime
        self.normal_open = normally_open

        if GPIO is None:
            self.fault = True
            self.fault_message = "RPi.GPIO not found"
            logging.warning(f"PinWatcher ({name}): Not initializing, RPi.GPIO not found")
            return

        self.edge = edge if edge is not None else GPIO.BOTH
        try:
            self.state = GPIO.input(self.pin) if self.normal_open else not GPIO.input(self.pin)
            GPIO.add_event_detect(self.pin, self.edge, callback=self._callback, bouncetime=self.bouncetime)
            logging.debug(f"PinWatcher ({name}): Initialized")
        except Exception as e:
            self.fault = True
            self.fault_message = str(e)
            logging.warning(f"PinWatcher ({name}): Error initializing: {e}")

    def _callback(self, pin):
        self.state = GPIO.input(self.pin) if self.normal_open else not GPIO.input(self.pin)
        logging.debug(f"PinWatcher ({self.name()}): Pin {pin} changed state to {self.state}")
        self.callback(pin)
        # Setup new event detect
        GPIO.remove_event_detect(self.pin)
        GPIO.add_event_detect(self.pin, self.edge, callback=self._callback, bouncetime=self.bouncetime)

    def name(self):
        return self._name

    def get_state(self):
        return {
            "on": self.enabled,
            "triggered": self.state,
            "active_for": 0,
        }

    def get_info(self):
        return {
            "name": self.name(),
            "pin": self.pin,
            "edge": self.edge,
            "bouncetime": self.bouncetime
        }

    def get_type(self):
        return "pin_watcher"

    def get_health(self):
        return {
            "online": True,
            "fault": self.fault,
            "reason": self.fault_message
        }

    def auto_state(self):
        return False
