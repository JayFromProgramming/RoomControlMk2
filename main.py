from Modules import RoomControl
import asyncio
import logging
import sqlite3

from Modules.RoomControl.AbstractSmartDevices import background

logging.basicConfig(level=logging.DEBUG,
                    format=f"%(asctime)s - %(name)s - %(thread)s - %(levelname)s - %(message)s",
                    datefmt='%H:%M:%S')

logging = logging.getLogger(__name__)
room_controller = RoomControl.RoomController()


async def main():
    logging.info("Starting main")

    while True:
        await asyncio.sleep(5)
        room_controller.refresh()


@background
def other_main():
    asyncio.new_event_loop()
    asyncio.run(main())


other_main()
room_controller.web_server.run()
