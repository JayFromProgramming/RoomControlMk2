import asyncio
import json
from typing import Optional

from Modules.RoomControl.SatelliteAPI.SatelliteDevice import SatelliteDevice
from loguru import logger as logging


class SatelliteLinkHandler:
    """
    Handles the connection to the satellite API.
    """

    def __init__(self, socket_reader: asyncio.StreamReader, socket_writer: asyncio.StreamWriter):
        """
        Initialize the connection handler with the websocket connection and room controller.
        """
        self.socket_writer : asyncio.StreamWriter = socket_writer
        self.socket_reader: asyncio.StreamReader = socket_reader
        self.uplink_task: Optional[asyncio.Task] = None
        self.downlink_task: Optional[asyncio.Task] = None
        self.uplink_queue: asyncio.Queue = asyncio.Queue()
        self.downlink_handler = None
        self.closed = False

    async def begin_handler(self, downlink_handler):
        """
        Begin handling the connection. This method should be called to start the connection handling process.
        """
        logging.info("Starting satellite connection handler")
        if not self.socket_writer or not self.socket_reader:
            logging.error("Socket writer or reader is not initialized")
            return
        self.downlink_handler = downlink_handler
        self.downlink_task = asyncio.create_task(self.handle_downlink())
        self.uplink_task = asyncio.create_task(self.handle_uplink())

    async def handle_downlink(self):
        """
        Handle the connection to the satellite. This method should keep the connection alive and process messages.
        """
        self.socket_reader._limit = 1024
        logging.info(f"Starting downlink handler for satellite connection [{self.socket_writer.get_extra_info('peername')}]")
        while True:
            try:
                # Read data from the socket
                data = await self.socket_reader.readuntil(b'\0')
                data = data[:-1]  # Remove the null byte
                if not data:
                    logging.info("Connection closed by satellite")
                    break
                message = data.decode('utf-8').strip()
                logging.info(f"Received data from satellite: {data}")
                # Process the message
                if self.downlink_handler is not None:
                    await self.downlink_handler(message)
                else:
                    logging.warning("No downlink handler set, cannot process message")
            except asyncio.IncompleteReadError:
                # Handle the case where the connection is closed unexpectedly
                logging.warning("Buffer overflow or connection closed unexpectedly")
            except json.JSONDecodeError as e:
                # Handle JSON decoding errors
                logging.error(f"Failed to decode JSON message from satellite: {e}")
                logging.exception(e)
            except OSError as e:
                # Handle connection reset errors
                logging.warning(f"OSError: {e}")
                break
            except Exception as e:
                # Handle exceptions, such as connection loss
                logging.error(f"Connection error: {e}")
                logging.exception(e)
                break
            except asyncio.CancelledError:
                # Handle cancellation of the task
                logging.info("Downlink handler task cancelled")
                return
        if self.closed:
            return
        await self.destroy()


    async def handle_uplink(self):
        """
        Handle asynchronous uplink communication with the satellite by sending messages that are in the uplink queue.
        """
        try:
            while True:
                message = await self.uplink_queue.get()
                logging.debug(f"Sending message to satellite: {message}")
                # Send the message to the satellite
                terminated_message = json.dumps(message) + '\0'  # Add null byte to terminate the message
                self.socket_writer.write(terminated_message.encode('utf-8'))
                # Validate that the downlink task is still running
                if self.downlink_task is None or self.downlink_task.done():
                    logging.warning("Downlink task has failed, terminating connection")
                    break
        except Exception as e:
            logging.error(f"Error sending message to satellite : {e}")
            logging.exception(e)
        except asyncio.CancelledError:
            # Handle cancellation of the task
            logging.info("Uplink handler task cancelled")
            return
        finally:
            if self.closed:
                return
            await self.destroy()
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

    def connection_alive(self) -> bool:
        """
        Check if the connection to the satellite is still alive.

        :return: True if the connection is alive, otherwise False.
        """
        return self.socket_writer is not None and not self.socket_writer.is_closing()

    async def destroy(self):
        """
        Clean up the connection handler by cancelling tasks and closing the websocket connection.
        """
        if self.closed:
            return
        self.closed = True
        if self.uplink_task:
            self.uplink_task.cancel()
        if self.downlink_task:
            self.downlink_task.cancel()
        if self.socket_reader:
            self.socket_reader.feed_eof()
        if self.socket_writer:
            self.socket_writer.close()
            await self.socket_writer.wait_closed()
        self.socket_writer = None
        self.socket_reader = None
        logging.info("Satellite connection handler destroyed")

