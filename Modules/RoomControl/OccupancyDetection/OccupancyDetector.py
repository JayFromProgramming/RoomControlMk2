from Modules.RoomControl.OccupancyDetection.BluetoothOccupancy import BluetoothDetector
import time

from Modules.RoomControl.Decorators import background
from Modules.RoomControl.OccupancyDetection.MTUNetOccupancy import NetworkOccupancyDetector

from loguru import logger as logging

from Modules.RoomModule import RoomModule
from Modules.RoomObject import RoomObject

try:
    import RPi.GPIO as GPIO
except ImportError:
    GPIO = None
    logging.warning("RPi.GPIO not found, GPIO will not be available")


class OccupancyDetector(RoomModule):

    def __init__(self, room_controller):
        super().__init__(room_controller)
        self.room_controller = room_controller
        self.database = room_controller.database
        self.database_init()
        self.sources = {}

        self.last_activity = 0  # type: int # Last time a user was detected either by door or motion sensor

        if GPIO:
            GPIO.setmode(GPIO.BOARD)

        results = self.database.get("""
            SELECT * FROM occupancy_sources
        """)

        enabled_sources = {}
        for name, enabled, _ in results:
            enabled_sources[name] = True if enabled == 1 else False

        self.blue_stalker = self.room_controller.get_object("BlueStalker")

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

