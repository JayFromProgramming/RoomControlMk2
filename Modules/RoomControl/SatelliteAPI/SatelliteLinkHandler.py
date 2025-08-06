import asyncio
import json
from typing import Optional

from Modules.RoomControl.SatelliteAPI.SatelliteDevice import SatelliteDevice
from loguru import logger as logging


class SatelliteLinkHandler:
    """
    Handles the connection to the satellite API.
    """

    NULL_TERM_ESCAPE  = 0x08  # Escape character for null termination in uplink messages
    NULL_TERM_REPLACE = 0x01  # Replacement character for null termination in uplink messages
    NULL_TERM_ESCAPE_REPLACE = 0x02  # Replacement character for escaped null termination in uplink messages

    def remove_null_bytes(self, message: bytes) -> bytes:
        """
        Remove null termination from the message.
        This method replaces the null termination character a different character to prevent premature termination

        :param message: The message to process.
        :return: The processed message without any null bytes.
        """
        if not message:
            return message
        filtered_message = bytearray()
        for byte in message:
            if byte == 0x00:
                # Replace the escape character with the replacement character
                filtered_message.append(self.NULL_TERM_ESCAPE)
                filtered_message.append(self.NULL_TERM_REPLACE)
            elif byte == self.NULL_TERM_ESCAPE:
                # Replace the escaped null termination character with the replacement character
                filtered_message.append(self.NULL_TERM_ESCAPE)
                filtered_message.append(self.NULL_TERM_ESCAPE_REPLACE)
            else:
                filtered_message.append(byte)
        # Validate that the message does contain any null bytes
        if b'\0' in filtered_message:
            logging.warning("Message contains null bytes, which should not happen")
        return filtered_message


    def __init__(self, socket_reader: asyncio.StreamReader, socket_writer: asyncio.StreamWriter):
        """
        Initialize the connection handler with the websocket connection and room controller.
        """
        self.socket_writer : asyncio.StreamWriter = socket_writer
        self.socket_reader: asyncio.StreamReader = socket_reader
        self.uplink_task: Optional[asyncio.Task] = None
        self.downlink_task: Optional[asyncio.Task] = None
        self.uplink_queue: asyncio.Queue = asyncio.Queue()
        self.uplink_lock: asyncio.Lock = asyncio.Lock()
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
        self.socket_reader._limit = 4096
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
                # logging.info(f"Received data from satellite: {data}")
                # Process the message
                if self.downlink_handler is not None:
                    await self.downlink_handler(message)
                else:
                    logging.warning("No downlink handler set, cannot process message")
            except asyncio.IncompleteReadError:
                # Handle the case where the connection is closed unexpectedly
                logging.warning("Buffer overflow or connection closed unexpectedly")
                break
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
                logging.debug("Downlink handler task cancelled")
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
                await self.uplink_lock.acquire()
                logging.debug(f"Sending message to satellite: {message}")
                # Send the message to the satellite
                terminated_message = '\b' + json.dumps(message) + '\0'  # Add null byte to terminate the message
                self.socket_writer.write(terminated_message.encode('utf-8'))
                await self.socket_writer.drain()  # Ensure the message is sent
                self.uplink_lock.release()
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

    async def uplink_new_firmware(self, firmware_file) -> bool:
        """
        Send a new firmware file to the satellite for updating.

        :param firmware_file: The path to the firmware file to send.
        """
        try:
            with open(firmware_file, 'rb') as f:
                firmware_data = f.read()
            firmware_len = len(firmware_data)
            await self.uplink_lock.acquire()
            logging.info(f"Sending firmware update start message to satellite")
            # Send firmware length as an unsigned 32-bit integer
            message = firmware_len.to_bytes(4, 'little')
            chunk = self.remove_null_bytes(message)  # Remove null bytes from the chunk
            message = b"\t" + chunk + b'\0'
            self.socket_writer.write(message)
            await self.socket_writer.drain()  # Ensure the message is sent
            logging.info(f"Sending firmware data to satellite, length: {firmware_len} bytes")
            self.uplink_lock.release()
            # Send the firmware data in 1024-byte chunks
            for i in range(0, firmware_len, 1024):
                chunk = firmware_data[i:i + 1024]
                if not chunk:
                    break
                chunk = self.remove_null_bytes(chunk)  # Remove null bytes from the chunk
                message = b"\t" + chunk + b'\0'  # Add null byte to terminate the message
                await self.uplink_lock.acquire()
                self.socket_writer.write(message)
                await self.socket_writer.drain()  # Ensure the message is sent
                self.uplink_lock.release()
            logging.info("Firmware update sent successfully")
            return True
        except Exception as e:
            logging.error(f"Failed to send firmware update: {e}")
            logging.exception(e)
            return False

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
        # release any locks
        if self.uplink_lock.locked():
            self.uplink_lock.release()
        self.socket_writer = None
        self.socket_reader = None
        logging.info("Satellite connection handler destroyed")

