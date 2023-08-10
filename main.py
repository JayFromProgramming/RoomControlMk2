
from loguru import logger as logging
import sys
import os

# Create a logs folder if it doesn't exist and make sure its permissions are correct
if not os.path.exists("logs"):
    os.mkdir("logs")
    os.chmod("logs", 0o777)

logging.remove()
logging.add(sys.stdout, level="INFO")
logging.add("logs/{time}.log", rotation="1 week", retention="1 hour", compression="zip", level="WARNING")

from Modules import RoomControl
import asyncio
from Modules.RoomControl.Decorators import background

room_controller = RoomControl.RoomController()


async def main():
    logging.info("Starting main")
    # Check if running on linux
    # if sys.platform == "linux":
        # Kill any process bound to port 47670
        # os.system("sudo kill -9 $(sudo lsof -t -i:47670)")
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
