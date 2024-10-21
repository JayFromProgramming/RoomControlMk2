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
        self.last_activity = 0  # type: int # Last time a user was detected either by door or motion sensor

        # if GPIO:
        #     GPIO.setmode(GPIO.BOARD)

        results = self.database.get("""
            SELECT * FROM occupancy_sources
        """)

        enabled_sources = {}
        for name, enabled, _ in results:
            enabled_sources[name] = True if enabled == 1 else False

        self.blue_stalkers = []
        self.blue_stalkers.append(self.room_controller.get_object("BlueStalker"))
        self.blue_stalkers.append(self.room_controller.get_object("BlueStalker2"))
        self.motion_detector = self.room_controller.get_object("MotionDetector")
        self.motion_detector.attach_event_callback(self.motion_detected, "motion_detected")

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
            # scanning_allowed = True
            # for source in self.sources.values():
            #     if not isinstance(source, BluetoothDetector):
            #         if source.enabled:
            #             scanning_allowed = False
            # if scanning_allowed:
            #     self.blue_stalker.high_frequency_scan_enabled = False
            # else:
            #     self.blue_stalker.high_frequency_scan_enabled = True
            time.sleep(5)

    def motion_detected(self, state):
        logging.info("Motion event received")
        self.last_activity = time.time()
        for stalker in self.blue_stalkers:
            try:
                stalker.emit_event("scan")
            except Exception as e:
                logging.error(f"Error emitting scan event: {e}")
                logging.exception(e)

    def bluetooth_offline(self):
        for stalker in self.blue_stalkers:
            health = stalker.get_health()
            if health is not None:
                if health["online"]:
                    return False
        return True

    def was_activity_recent(self, seconds=60):
        return self.last_activity + seconds > time.time()

    def is_here(self, device):
        for source in self.blue_stalkers:
            try:
                if source.get_value("occupants") is not None:
                    for uuid, details in source.get_value("occupants").items():
                        if int(uuid) == device:
                            return True
            except Exception as e:
                logging.error(f"Error checking if device is here: {e}")
        return False

    def get_name(self, device):
        for source in self.blue_stalkers:
            try:
                if device in source.get_value("targets").keys():
                    return source.get_value("targets")[device]["name"]
            except Exception as e:
                logging.error(f"Error getting device name: {e}")
        return "Unknown"

    def get_all_devices(self):
        devices = []
        for source in self.blue_stalkers:
            devices.extend(source.get_value("targets").keys())
        return devices

    def get_device(self, device_id):
        return "Not implemented yet"
        for device in self.blue_stalkers:
            if device.name() == device_id:
                return device
