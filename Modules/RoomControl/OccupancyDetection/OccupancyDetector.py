from Modules.RoomControl.OccupancyDetection.BluetoothOccupancy import BluetoothDetector
import time

from Modules.RoomControl.AbstractSmartDevices import background
from Modules.RoomControl.OccupancyDetection.MTUNetOccupancy import NetworkOccupancyDetector

from loguru import logger as logging

try:
    import RPi.GPIO as GPIO
except ImportError:
    GPIO = None
    logging.warning("RPi.GPIO not found, GPIO will not be available")


class OccupancyDetector:

    def __init__(self, database):
        self.database = database
        self.database_init()
        self.sources = {}

        self.last_activity = 0  # type: int # Last time a user was detected either by door or motion sensor

        self.blue_stalker = BluetoothDetector(self.database, high_frequency_scan_enabled=False if GPIO else True)
        # self.net_stalker = NetworkOccupancyDetector(self.database)

        if GPIO:
            GPIO.setmode(GPIO.BOARD)

        results = self.database.get("""
            SELECT * FROM occupancy_sources
        """)

        enabled_sources = {}
        for name, enabled, _ in results:
            enabled_sources[name] = True if enabled == 1 else False

        self.motion_pin = PinWatcher("motion", 11, self.motion_detected, bouncetime=200,
                                     enabled=enabled_sources["motion"], database=self.database)
        self.door_pin = PinWatcher("door", 15, self.motion_detected, bouncetime=200,
                                   enabled=enabled_sources["door"], database=self.database)

        self.sources = {
            "bluetooth": self.blue_stalker,
            "motion": self.motion_pin,
            "door": self.door_pin
        }
        self.periodic_update()

    def database_init(self):
        self.database.run("""
        CREATE TABLE IF NOT EXISTS occupancy_sources (
        name text, enabled BOOLEAN DEFAULT TRUE, fault_state TEXT DEFAULT null)
        """, commit=True)
        # Add default sources

        results = self.database.get("""
        SELECT * FROM occupancy_sources""")
        if len(results) == 0:
            self.database.run("""
            INSERT OR IGNORE INTO occupancy_sources (name) VALUES ("bluetooth")
            """, commit=True)
            self.database.run("""
            INSERT OR IGNORE INTO occupancy_sources (name) VALUES ("motion")
            """, commit=True)
            self.database.run("""
            INSERT OR IGNORE INTO occupancy_sources (name) VALUES ("door")
            """, commit=True)

    @background
    def periodic_update(self):
        while True:
            if GPIO is None:
                break
            scanning_allowed = True
            for source in self.sources.values():
                if not isinstance(source, BluetoothDetector):
                    if source.enabled:
                        scanning_allowed = False
            if scanning_allowed:
                self.blue_stalker.high_frequency_scan_enabled = False
            else:
                self.blue_stalker.high_frequency_scan_enabled = True
            time.sleep(5)

    def motion_detected(self, pin):
        logging.info("Activity Detected on pin {}".format(pin))
        self.last_activity = time.time()
        self.blue_stalker.should_scan()

    def bluetooth_offline(self):
        return not self.blue_stalker.online

    def was_activity_recent(self, seconds=60):
        return self.last_activity + seconds > time.time()

    def is_here(self, device):
        return self.blue_stalker.is_here(device)

    def on_campus(self, device):
        return self.net_stalker.is_on_campus(device)

    def get_name(self, device):
        return self.blue_stalker.get_name(device)

    def get_all_devices(self):
        return self.sources.values()

    def get_device(self, device_id):
        for device in self.sources.values():
            if device.name() == device_id:
                return device


class PinWatcher:

    def __init__(self, name, pin, callback: callable, edge=None, bouncetime=200, normally_open=True,
                 enabled=True, database=None):
        self.online = True
        self.fault = False
        self.fault_message = ""
        self.pin = pin  # Pin number
        self.state = None  # None = Unknown, True = On, False = Off
        self._name = name  # Name of the device
        self.enabled = enabled  # Is the device enabled for detection

        self._last_rising = 0  # Last time the device was triggered
        self._last_falling = 0  # Last time the device was triggered

        self.callback = callback
        self.edge = None
        self.bouncetime = bouncetime
        self.normal_open = normally_open
        self.database = database

        if GPIO is None:
            self.fault = True
            self.fault_message = "RPi.GPIO not found"
            logging.warning(f"PinWatcher ({name}): Not initializing, RPi.GPIO not found")
            return

        self.edge = edge if edge is not None else GPIO.BOTH
        try:
            GPIO.setup(self.pin, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
            self.state = GPIO.input(self.pin) if self.normal_open else not GPIO.input(self.pin)
            GPIO.add_event_detect(self.pin, self.edge, callback=self._callback, bouncetime=self.bouncetime)
            logging.debug(f"PinWatcher ({name}): Initialized")
        except Exception as e:
            self.fault = True
            self.fault_message = str(e)
            logging.warning(f"PinWatcher ({name}): Error initializing: {e}")

    def _callback(self, pin):
        self.state = GPIO.input(self.pin) if self.normal_open else not GPIO.input(self.pin)

        if self.state:  # If the device is active
            self._last_rising = time.time()
        else:
            self._last_falling = time.time()

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
            "active_for": 0 if not self.state else time.time() - self._last_rising,
            "last_active": self._last_rising,
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

    @property
    def on(self):
        return self.enabled

    @on.setter
    def on(self, value):
        self.database.run("UPDATE occupancy_sources SET enabled = ? WHERE name = ?", (value, self.name()), commit=True)
        self.enabled = value
