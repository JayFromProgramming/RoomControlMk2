from Modules import RoomControl
import asyncio
import logging
import sqlite3


logging.basicConfig(level=logging.DEBUG,
                    format=f"%(asctime)s - %(name)s - %(thread)s - %(levelname)s - %(message)s",
                    datefmt='%H:%M:%S')

logging = logging.getLogger(__name__)


async def main():
    logging.info("Starting main")
    room_controller = RoomControl.RoomController()
    while True:
        await asyncio.sleep(5)
        room_controller.refresh()



asyncio.run(main())
