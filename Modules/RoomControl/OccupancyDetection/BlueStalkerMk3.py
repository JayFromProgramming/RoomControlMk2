import time

from loguru import logger as logging
from Modules.RoomControl.Decorators import background
from Modules.RoomModule import RoomModule
from Modules.RoomObject import RoomObject
import multiprocessing
import asyncio
bluetooth_avail = True
try:
    from bleak import BleakScanner, BleakClient
except ImportError:
    logging.error("Failed to import bleak, please run 'pip install bleak' to install it")
    BleakScanner = None

# try:
#     import bluetooth
# except ImportError:
#     logging.error("Bluetooth not available")
#     bluetooth_avail = False

multiprocessing.set_start_method("spawn", force=True)


class BlueStalkerMk3(RoomModule):
    requires_async = True

    def __init__(self, room_controller):
        super().__init__(room_controller)
        if BleakScanner is None:
            logging.error("Aborting BluestalkerMk3 module initialization, bleak is not installed")
            return
        # if not bluetooth_avail:
        #     logging.error("Aborting BluestalkerMk3 module initialization, bluetooth is not available")
        #     return
        self.room_controller = room_controller
        self.blue_stalker = BlueStalkerMk3Object(self.room_controller)


class BlueStalkerMk3Object(RoomObject):

    def __init__(self, room_controller):
        super().__init__("BlueStalkerMk3", "bluetooth_occupancy")
        self.room_controller = room_controller
        self.target_addresses = []
        self.occupants = {}
        self.targets = {}
        self.get_targets_from_db()
        self.ipc_queue = multiprocessing.Queue()
        self.bluestalker_process = BlueStalkerMk3Process(self.ipc_queue, self.target_addresses)
        self.bluestalker_process.start()
        self.data_reader()
        self.set_value("occupants", self.occupants)
        self.set_value("targets", self.targets)
        self.set_value("occupied", None)
        room_controller.attach_object(self)

    def get_targets_from_db(self):
        database = self.room_controller.database
        targets = database.get_table("bluetooth_targets")
        for target in targets.get_all():
            self.target_addresses.append(target["address"])
            self.targets.update({target["uuid"]: {"address": target["address"], "name": target["name"]}})
        self.set_value("targets", self.targets)

    def get_target_by_address(self, address):
        for target in self.targets:
            if self.targets[target]["address"] == address:
                return target
        return None

    def update_occupant(self, data: dict):
        target = self.get_target_by_address(data["address"])
        if not target:
            return
        if data["found"]:
            self.occupants.update({target: self.targets[target]})
        elif data["missed_scans"] > 15:
            self.occupants.pop(target, None)
        self.set_value("occupants", self.occupants)
        if len(self.occupants) > 0:
            self.set_value("occupied", True)
        else:
            self.set_value("occupied", False)

    @background
    def data_reader(self):
        while True:
            if not self.ipc_queue.empty():
                data = self.ipc_queue.get()
                self.update_occupant(data)
            if not self.bluestalker_process.is_alive():
                logging.error("BlueStalkerMk3 process died, restarting")
                self.bluestalker_process = BlueStalkerMk3Process(self.ipc_queue, self.targets)
                self.bluestalker_process.start()
            time.sleep(1)

    def get_state(self):
        return self.get_values()

    def get_health(self):
        return {
            "online": self.bluestalker_process.is_alive(),
            "fault": False,
            "reason": None
        }


class BlueStalkerMk3Process(multiprocessing.Process):

    def __init__(self, ipc_queue, targets=None):
        super().__init__()
        logging.info(f"Starting BlueStalkerMk2 process with targets: {targets}")
        self.ipc_queue = ipc_queue
        self.scanner = BleakScanner()
        self.targets = targets
        self.target_last_seen = {}
        self.scan_failures = 0
        for target in self.targets:
            self.target_last_seen[target] = 0
        self.running = True

    def run(self):
        asyncio.run(self.main())

    async def scan(self):
        for target in self.targets:
            try:
                device = await self.scanner.find_device_by_address(target, timeout=2)
                if device:
                    self.target_last_seen[target] = 0
                    self.ipc_queue.put({"address": target, "found": True, "missed_scans": 0})
                else:
                    self.target_last_seen[target] += 1
                    self.ipc_queue.put({"address": target, "found": False, "missed_scans": self.target_last_seen[target]})
            except Exception as e:
                logging.error(f"Error scanning for device: {e}")
                if self.scan_failures == 0:
                    logging.exception(e)
                self.scan_failures += 1
            else:
                self.scan_failures = 0

    async def main(self):
        logging.info("BlueStalkerMk3 async main started")
        while self.running:
            if self.scan_failures > 5:
                logging.error("Too many scan failures, halting scanning")
                await asyncio.sleep(99999)
            await self.scan()
            await asyncio.sleep(5)
