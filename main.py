from loguru import logger as logging
import sys
import os

from Modules import RoomControl
import asyncio
from Modules.RoomControl.Decorators import background

# Create a logs folder if it doesn't exist and make sure its permissions are correct
if not os.path.exists("logs"):
    os.mkdir("logs")
    os.chmod("logs", 0o777)

logging.remove()
logging.add(sys.stdout, level="INFO")
logging.add("logs/{time}.log", rotation="1 week", retention="1 hour", compression="zip", level="WARNING")

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


async def webserver_runner():
    await asyncio.sleep(5)
    logging.info("Starting web servers")
    sites = []
    for module in room_controller.get_modules():
        # if hasattr(module, "wait_for_ready"):
        #     module.wait_for_ready()
        # Collect any aiohttp servers and run use asyncio.gather to run them all at once

        if hasattr(module, "is_webserver") and getattr(module, "get_site", None) is not None:
            try:
                logging.info(f"Found web server {module}")
                sites.append(await module.get_site())
            except Exception as e:
                logging.error(f"Error starting web server: {e}")
                logging.exception(e)
    if len(sites) > 0:
        await asyncio.gather(*(site.start() for site in sites))

    logging.info("Web servers started")
    while True:
        await asyncio.sleep(9999)


# room_controller.web_server.run()
asyncio.run(webserver_runner())
