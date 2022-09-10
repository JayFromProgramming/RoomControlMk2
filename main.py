from Modules import RoomControl
import asyncio
import logging
import sqlite3

room_controller = RoomControl.RoomController()

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', datefmt='%H:%M:%S',
                    handlers=[logging.FileHandler("logs.log"), logging.StreamHandler()])


async def main():
    logging.info("Starting main")
    await asyncio.sleep(600000)


asyncio.run(main())
