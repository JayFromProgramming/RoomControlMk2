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

    def __init__(self, database: sqlite3.Connection, connect_on_queue: bool = False):
        # Target file is a json file that contains bluetooth addresses, name, and role
        self.database = database
        self.init_database()

        self.sockets = {}
        self.connect_on_queue = connect_on_queue
        self.last_update = 0
        self.enabled = True
        self.scan_lockout_time = 0

        self.heartbeat_device = "38:1D:D9:F7:6D:44"
        self.heartbeat_alive = False  # If the heartbeat device is alive

        if bluetooth is not None:
            self.online = True
            self.fault = False
            self.fault_message = ""
        else:
            self.online = True
            self.fault = False
            self.fault_message = "Bluetooth not available"

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

    def should_scan(self):
        """Called externally to tell that it is time to scan"""
        if self.scan_lockout_time > datetime.datetime.now().timestamp():
            return False
        self.refresh(scan_allowed=True)
        self.scan_lockout_time = datetime.datetime.now().timestamp() + 15

    @background
    def scan(self, scan_allowed):
        logging.info("BlueStalker: Scanning for bluetooth devices")

        try:
            # Check if the heartbeat device is still connected
            if self.heartbeat_alive:
                self.conn_is_alive(self.sockets[self.heartbeat_device], self.heartbeat_device, is_heartbeat=True)
            else:
                self.connect(self.heartbeat_device, is_heartbeat=True)
        except Exception as e:
            logging.error(f"BlueStalker: Error checking heartbeat device: {e}")

        targets = self.database.cursor().execute("SELECT * FROM bluetooth_targets").fetchall()
        for target in targets:
            if conn := self.sockets.get(target[1]):  # If the socket is already open
                self.conn_is_alive(conn, target[1])  # Check if the connection is still alive
            else:
                if scan_allowed:
                    self.connect(target[1])  # Else attempt to connect to the device

        self.last_update = datetime.datetime.now().timestamp()  # Update the last update time

    def determine_health(self):
        if self.heartbeat_alive:
            self.online = True
            self.fault = False
            self.fault_message = ""
        else:
            # If the heartbeat device is not alive and there are no other devices connected
            # Then the bluetooth detector is offline
            if len(self.sockets) == 0:
                self.fault = True
                self.online = False
                self.fault_message = "Radio Unresponsive"
            else:
                self.fault = True
                self.online = True
                self.fault_message = "No Heartbeat"

    @background
    def refresh(self):
        logging.info(f"BlueStalker: Refresh loop started scanning is {'not allowed' if self.connect_on_queue else 'allowed'}")
        while True:
            try:
                if self.enabled:
                    self.scan(not self.connect_on_queue)
                time.sleep(30)
                self.determine_health()
            except Exception as e:
                logging.error(f"BluetoothOccupancy: Refresh loop failed with error {e}")
                break
        self.fault = True
        self.fault_message = "Refresh loop exited"

    @background
    def connect(self, address, is_heartbeat=False):
        if bluetooth is None:
            self.fault = True
            self.fault_message = "Bluetooth not available"
            return
        sock = bluetooth.BluetoothSocket(bluetooth.RFCOMM)
        sock.setblocking(True)  # Set the socket to non-blocking
        try:
            logging.info(f"BlueStalker: Connecting to {address}, timeout {sock.gettimeout()}")
            sock.connect((address, 1))  # Start the connection (Will fail with EINPROGRESS)
        except bluetooth.btcommon.BluetoothError as e:
            if e.__str__() == "[Errno 111] Connection refused":  # Connection refused still counts as a connection as
                # the device had to be in range to refuse the connection
                logging.error(f"BlueStalker: Connection to address {address} refused, device is in range")
                if not is_heartbeat:
                    self.update_occupancy(address, True)
                else:
                    self.heartbeat_alive = True
                return
            elif e.__str__() == "[Errno 115] Operation now in progress":  # This is the error we expect to see
                logging.info(f"BlueStalker: Connection to {address} is in progress")
                self.sockets[address] = sock  # Add the socket to the list of sockets
                time.sleep(2.5)  # Wait for the connection to complete
                self.conn_is_alive(sock, address)  # Check if the connection is still alive
                return
            else:  # Any other error is unexpected
                logging.error(f"BlueStalker: Connection to address {address} failed with error {e}")
                if not is_heartbeat:
                    self.update_occupancy(address, False)
                else:
                    self.heartbeat_alive = False
                return
        except OSError as e:  # Any additional errors that the OS throws are caught here
            logging.error(f"BlueStalker: Failed to connect to {address} with error {e}")
            if not is_heartbeat:
                self.update_occupancy(address, False)
            else:
                self.heartbeat_alive = False
            return
        else:
            logging.info(f"BlueStalker: Connected to {address}")
            self.sockets[address] = sock
            if not is_heartbeat:
                self.update_occupancy(address, True)
            else:
                self.heartbeat_alive = True

    @background
    def conn_is_alive(self, connection, address, is_heartbeat=False):
        logging.info(f"BlueStalker: Checking if {address} is alive")
        try:
            connection.getpeername()
        except bluetooth.BluetoothError as e:
            logging.info(f"BlueStalker: Connection to {address} is dead, reason: {e}")
            if not is_heartbeat:
                self.update_occupancy(address, False)
            else:
                self.heartbeat_alive = False
            self.sockets.pop(address)
        except OSError:
            logging.debug("Connection lost")
            connection.close()
            if not is_heartbeat:
                self.update_occupancy(address, False)
            else:
                self.heartbeat_alive = False
            self.sockets.pop(address)
        else:
            logging.debug(f"Connection to {address} is alive")
            if not is_heartbeat:
                self.update_occupancy(address, True)
            else:
                self.heartbeat_alive = True

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

    def get_occupants_names(self):
        """Gets current occupants and only returns their names"""
        occupants = self.get_occupancy()
        occupants_names = []
        for occupant in occupants:
            if occupants[occupant]["present"]:
                occupants_names.append(occupant)
        return occupants_names

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

    ### API Methods ###

    @property
    def on(self):
        return self.enabled

    @on.setter
    def on(self, value):
        self.enabled = value

    def name(self):
        return "blue_stalker"

    def get_state(self):
        return {
            "on": self.enabled,
            "auto_scan": not self.connect_on_queue,
            "occupied": self.is_occupied(),
            "occupants": self.get_occupants_names()
        }

    def get_info(self):
        return {
            "last_update": self.last_update
        }

    def get_health(self):
        return {
            "online": self.online,
            "fault": self.fault,
            "reason": self.fault_message
        }

    def get_type(self):
        return "blue_stalker"

    def auto_state(self):
        return False
