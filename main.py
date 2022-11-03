import logging

logging.basicConfig(level=logging.INFO,
                    format=r"%(levelname)s - %(threadName)s - %(name)s - %(funcName)s - %(message)s",
                    datefmt='%H:%M:%S')


from Modules import RoomControl
import asyncio
from Modules.RoomControl.AbstractSmartDevices import background

room_controller = RoomControl.RoomController()


async def main():
    logging.info("Starting main")
    while True:
        await asyncio.sleep(5)
        room_controller.refresh()


@background
def other_main():
    asyncio.new_event_loop()

    # logging = logging.getLogger(__name__)
    asyncio.run(main())


other_main()
room_controller.web_server.run()
