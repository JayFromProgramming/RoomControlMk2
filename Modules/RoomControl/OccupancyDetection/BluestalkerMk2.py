from loguru import logger as logging
from Modules.RoomControl.Decorators import background
from Modules.RoomModule import RoomModule
from Modules.RoomObject import RoomObject
import asyncio

try:
    from bleak import BleakScanner, BleakClient
except ImportError:
    logging.error("Failed to import bleak, please run 'pip install bleak' to install it")
    BleakScanner = None


class BluestalkerMk2(RoomModule):
    requires_async = True

    def __init__(self, room_controller):
        super().__init__(room_controller)
        self.room_controller = room_controller
        self.blue_stalker = None

    async def start(self):
        self.blue_stalker = BluestalkerMk2Object(self.room_controller)
        await self.blue_stalker.start()


class BluestalkerMk2Object(RoomObject):
    object_type = "Bluestalker"

    def __init__(self, room_controller):
        super().__init__("BluestalkerMk2", "Bluestalker")
        self.targets = []
        self.occupants = {}
        self.room_controller = room_controller
        self.database = room_controller.database

        self.set_value("occupants", {})
        self.set_value("occupied", None)

        table = self.database.get_table("bluetooth_targets")
        for row in table.get_rows():
            self.targets.append((row["name"], row["address"]))
            self.occupants[row["name"]] = False

        logging.info(f"Found {len(self.targets)} bluetooth targets")
        self.room_controller.attach_object(self)

    async def start(self):
        try:
            logging.info(f"Starting Bluestalker2 connections to {len(self.targets)} targets")
            connection_tasks = []

            discovered = await BleakScanner.discover()
            matches = [device for device in discovered if device.address in [target[1] for target in self.targets]]

            logging.info(f"Found {len(matches)} devices out of {len(self.targets)}")

            for target in self.targets:
                connection_tasks.append(self.establish_connection(target))

            await asyncio.gather(*connection_tasks)
        except Exception as e:
            logging.error(f"Failed to start Bluestalker2: {e}")

    async def establish_connection(self, target):
        return
        target_name, target_device = target
        try:
            logging.info(f"Connecting to {target_name} ({target_device})")
            self.occupants[target_name] = True
            async with BleakClient(target_device) as client:
                logging.warning(f"Lost connection to {client.address}")
                self.occupants[target_name] = False
        except Exception as e:
            logging.error(f"Failed to connect to ({target_name}, {target_device}): {e}")
            self.occupants[target_name] = False
        finally:
            logging.warning(f"Disconnected from {target_name} ({target_device})")

    def get_state(self):
        return {
            "targets": self.targets,
            "occupants": self.occupants
        }