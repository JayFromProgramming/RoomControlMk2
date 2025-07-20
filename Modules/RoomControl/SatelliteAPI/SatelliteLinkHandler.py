import asyncio
from typing import Optional

from aiohttp import web

from Modules.RoomControl.SatelliteAPI.SatelliteDevice import SatelliteDevice
from loguru import logger as logging


class SatelliteLinkHandler:
    """
    Handles the connection to the satellite API.
    """

    def __init__(self, websocket_connection):
        """
        Initialize the connection handler with the websocket connection and room controller.

        :param websocket_connection: The websocket connection to the satellite.
        """
        self.websocket_connection = websocket_connection

        self.uplink_task: Optional[asyncio.Task] = None
        self.downlink_task: Optional[asyncio.Task] = None
        self.uplink_queue: asyncio.Queue = asyncio.Queue()
        self.downlink_queue: asyncio.Queue = asyncio.Queue()

    async def begin_handler(self):
        """
        Begin handling the connection. This method should be called to start the connection handling process.
        """
        logging.info("Starting satellite connection handler")
        self.downlink_task = asyncio.create_task(self.handle_downlink())
        self.uplink_task = asyncio.create_task(self.handle_uplink())

    async def handle_downlink(self):
        """
        Handle the connection to the satellite. This method should keep the connection alive and process messages.
        """
        try:
            async for message in self.websocket_connection:
                if message.type == web.WSMsgType.TEXT:
                    logging.info(f"Received message from satellite [{self.websocket_connection.remote}]: {message.data}")

                    # Here you can add logic to handle the message and update the satellite device
                elif message.type == web.WSMsgType.ERROR:
                    logging.error(f"WebSocket error: {self.websocket_connection.exception()}")
                    break
        except Exception as e:
            # Handle exceptions, such as connection loss
            logging.error(f"Connection error: {e}")
        finally:
            await self.websocket_connection.close()

    async def handle_uplink(self):
        """
        Handle asynchronous uplink communication with the satellite by sending messages that are in the uplink queue.
        """
        while True:
            try:
                message = await self.uplink_queue.get()
                if message is None:  # Exit condition
                    break
                # Send the message to the satellite
                await self.websocket_connection.send_str(message)
            except Exception as e:
                logging.error(f"Error sending message to satellite [{self.websocket_connection.remote}]: {e}")
            finally:
                self.uplink_queue.task_done()

    def send_uplink(self, message):
        """
        Send a message to the satellite by adding it to the uplink queue.

        :param message: The message to send.
        """
        if self.uplink_task is not None and not self.uplink_task.done():
            self.uplink_queue.put_nowait(message)
        else:
            logging.warning("Uplink task is not running, cannot send message")

    def get_downlink(self) -> Optional[str]:
        """
        Get a message from the downlink queue.

        :return: The message if available, otherwise None.
        """
        if not self.downlink_queue.empty():
            return self.downlink_queue.get_nowait()
        return None

    def connection_alive(self) -> bool:
        """
        Check if the connection to the satellite is still alive.

        :return: True if the connection is alive, otherwise False.
        """
        return self.websocket_connection and not self.websocket_connection.closed

    async def destroy(self):
        """
        Clean up the connection handler by cancelling tasks and closing the websocket connection.
        """
        if self.uplink_task:
            self.uplink_task.cancel()
        if self.downlink_task:
            self.downlink_task.cancel()
        if self.websocket_connection:
            await self.websocket_connection.close()
        logging.info("Satellite connection handler destroyed")

