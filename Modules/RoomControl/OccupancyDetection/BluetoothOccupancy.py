import datetime
import json
import logging
import sqlite3
import time

try:
    import bluetooth
except ImportError:
    logging.error("Bluetooth not available")
    bluetooth = None

from Modules.RoomControl.AbstractSmartDevices import background

logging = logging.getLogger(__name__)


class BluetoothDetector:

    def __init__(self, database: sqlite3.Connection):
        # Target file is a json file that contains bluetooth addresses, name, and role
        self.database = database
        self.init_database()

        self.sockets = {}

        self.last_update = 0
        self.refresh()

    def init_database(self):
        cursor = self.database.cursor()
        cursor.execute("CREATE TABLE IF NOT EXISTS bluetooth_targets"
                       " (uuid integer constraint table_name_pk primary key "
                       "autoincrement, address TEXT UNIQUE, name TEXT, role TEXT)")
        cursor.execute("CREATE TABLE IF NOT EXISTS bluetooth_occupancy (uuid INTEGER UNIQUE, in_room BOOLEAN, last_changed INTEGER)")
        cursor.close()

    def add_target(self, address: str, name: str, role: str):
        cursor = self.database.cursor()
        # Make sure the target is not already in the database
        cursor.execute("SELECT * FROM bluetooth_targets WHERE address=?", (address,))
        if cursor.fetchone() is None:
            cursor.execute("INSERT INTO bluetooth_targets (address, name, role) VALUES (?, ?, ?)",
                           (address, name, role))
            self.database.commit()
            logging.info(f"Added {name} to the target list")
        else:
            cursor.execute("UPDATE bluetooth_targets SET name=?, role=? WHERE address=?",
                           (name, role, address))
            self.database.commit()
            logging.warning(f"Target [{name}] already exists in database, updating instead")
        cursor.close()

    @background
    def refresh(self):
        while True:
            logging.info("Scanning for bluetooth devices")
            targets = self.database.cursor().execute("SELECT * FROM bluetooth_targets").fetchall()
            for target in targets:
                if conn := self.sockets.get(target[1]):  # If the socket is already open
                    self.conn_is_alive(conn, target[1])  # Check if the connection is still alive
                else:
                    self.connect(target[1])  # Else attempt to connect to the device
            self.last_update = datetime.datetime.now().timestamp() # Update the last update time
            time.sleep(30)

    @background
    def connect(self, address):
        if bluetooth is None:
            return
        sock = bluetooth.BluetoothSocket(bluetooth.RFCOMM)
        sock.setblocking(False)  # Set the socket to non-blocking
        try:
            logging.info(f"Connecting to {address}, timeout {sock.gettimeout()}")
            sock.connect((address, 1))
        except bluetooth.btcommon.BluetoothError as e:
            if e.__str__() == "timed out":
                logging.warning(f"Connection to {address} timed out")
                self.update_occupancy(address, False)
            elif e.__str__() == "[Errno 111] Connection refused":
                logging.error(f"Connection to address {address} was refused with error {e}")
                # Because the connection was refused, we can assume that the device is in the room, so we update the database
                self.update_occupancy(address, True)
                return
            elif e.__str__() == "[Errno 115] Operation now in progress":
                logging.info(f"Connection to {address} is in progress")
                self.sockets[address] = sock
                return
            else:
                logging.error(f"Connection to address {address} failed with error {e}")
                self.update_occupancy(address, False)
                return
        except OSError as e:
            logging.error(f"Failed to connect to {address} with error {e}")
            self.update_occupancy(address, False)
            return
        else:
            logging.info(f"Connected to {address}")
            self.sockets[address] = sock
            self.update_occupancy(address, True)

    @background
    def conn_is_alive(self, connection, address):
        logging.info(f"Checking if {address} is alive")
        try:
            connection.getpeername()
        except bluetooth.BluetoothError as e:
            logging.info(f"Connection to {address} is dead, reason: {e}")
            self.update_occupancy(address, False)
            self.sockets.pop(address)
        except OSError:
            logging.debug("Connection lost")
            connection.close()
            self.update_occupancy(address, False)
            self.sockets.pop(address)
        else:
            logging.debug(f"Connection to {address} is alive")
            self.update_occupancy(address, True)

    def detailed_status(self):
        return {
            "last_update": self.last_update
        }

    def update_occupancy(self, address, in_room):
        # Get the UUID of the mac address
        cursor = self.database.cursor()
        cursor.execute("SELECT uuid FROM bluetooth_targets WHERE address=?", (address,))
        uuid = cursor.fetchone()[0]
        cursor.close()
        if uuid == 0:
            logging.error(f"Failed to get UUID for {address}")
            return
        # Check if an occupancy entry exists for the address
        self.database.lock.acquire()
        cursor = self.database.cursor()
        cursor.execute("SELECT * FROM bluetooth_occupancy WHERE uuid=?", (uuid,))
        if cursor.fetchone() is None:
            # Check if the db state matches in_room, if it is, we don't need to update the database
            cursor.execute("INSERT INTO bluetooth_occupancy (uuid, in_room, last_changed) VALUES (?, ?, ?)",
                           (uuid, in_room, datetime.datetime.now().timestamp()))

            self.database.commit()
            self.database.lock.release()
        else:
            cursor.execute("UPDATE bluetooth_occupancy SET in_room=?, last_changed=? WHERE uuid=?",
                           (in_room, datetime.datetime.now().timestamp(), uuid))
            self.database.commit()
            self.database.lock.release()

    def get_occupancy(self):
        cursor = self.database.cursor()
        cursor.execute("SELECT * FROM bluetooth_occupancy")
        occupancy = cursor.fetchall()
        cursor.close()
        # Get the names of the devices combine this with the occupancy
        cursor = self.database.cursor()
        cursor.execute("SELECT * FROM bluetooth_targets")
        targets = cursor.fetchall()
        cursor.close()

        occupancy_info = {}
        for target in targets:
            for device in occupancy:
                if target[0] == device[0]:
                    present = True if device[1] == 1 else False
                    occupancy_info[target[2]] = {"present": present, "last_changed": device[2], "uuid": target[0]}

        return occupancy_info

    def is_occupied(self):
        cursor = self.database.cursor()
        cursor.execute("SELECT * FROM bluetooth_occupancy")
        occupancy = cursor.fetchall()
        cursor.close()
        for device in occupancy:
            if device[1] == 1:
                return True
        return False

    def get_combined_target_info(self, uuid):

        cursor = self.database.cursor()
        cursor.execute("SELECT * FROM bluetooth_occupancy WHERE uuid=?", (uuid,))
        device = cursor.fetchone()
        cursor.close()
        # Get the names of the devices combine this with the occupancy
        cursor = self.database.cursor()
        cursor.execute("SELECT * FROM bluetooth_targets WHERE uuid=?", (uuid,))
        target = cursor.fetchone()
        cursor.close()

        present = True if device[1] == 1 else False
        return {"present": present, "last_changed": device[2], "uuid": target[0]}

    def is_here(self, uuid):
        cursor = self.database.cursor()
        cursor.execute("SELECT * FROM bluetooth_occupancy WHERE uuid=?", (uuid,))
        device = cursor.fetchone()
        if device is None:
            return None
        cursor.close()
        return True if device[1] == 1 else False

    def get_name(self, uuid):
        cursor = self.database.cursor()
        cursor.execute("SELECT * FROM bluetooth_targets WHERE uuid=?", (uuid,))
        device = cursor.fetchone()
        if device is None:
            return None
        cursor.close()
        return device[2]

