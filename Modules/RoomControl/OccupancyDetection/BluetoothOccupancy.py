import datetime
import json
import logging
import sqlite3

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
        cursor.execute("CREATE TABLE IF NOT EXISTS bluetooth_occupancy (uuid INTEGER, in_room BOOLEAN, last_changed INTEGER)")
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
        logging.info("Scanning for bluetooth devices")
        targets = self.database.cursor().execute("SELECT * FROM bluetooth_targets").fetchall()
        for target in targets:
            if target[1] in self.sockets:
                self.conn_is_alive(target[1])
            else:
                self.connect(target[1])

    @background
    def connect(self, address):
        logging.debug(f"Connecting to {address}")
        print(f"Connecting to {address}")

        if bluetooth is None:
            return

        try:
            sock = bluetooth.BluetoothSocket(bluetooth.RFCOMM)
            sock.settimeout(5)
            sock.connect((address, 1))
            sock.send("Hello")
        except bluetooth.btcommon.BluetoothError as e:
            logging.error(f"Connection to address {address} was refused with error {e}")
            # Because the connection was refused, we can assume that the device is in the room, so we update the database
            self.update_occupancy(address, True)
            return
        except OSError as e:
            logging.error(f"Failed to connect to {address} with error {e}")
            return
        else:
            logging.info(f"Connected to {address}")
            self.sockets[address] = sock
            self.update_occupancy(address, True)

    @background
    def conn_is_alive(self, connection):
        print(f"Checking if {connection} is alive")
        try:
            connection.send("ping")
            connection.recv(1024)
        except OSError:
            logging.debug("Connection lost")
            print("Connection lost")
            connection.close()
            self.sockets.pop(connection)

    def detailed_status(self):
        return {
            "occupancy": self.occupancy_info,
            "targets": self.target_list,
            "last_update": self.last_update
        }

    def update_occupancy(self, address, in_room):
        # Get the UUID of the mac address
        cursor = self.database.cursor()
        cursor.execute("SELECT uuid FROM bluetooth_targets WHERE address=?", (address,))
        uuid = cursor.fetchone()[0]
        cursor.close()
        # Check if an occupancy entry exists for the address
        cursor = self.database.cursor()
        cursor.execute("SELECT * FROM bluetooth_occupancy WHERE uuid=?", (address,))
        if cursor.fetchone() is None:
            cursor.execute("INSERT INTO bluetooth_occupancy (uuid, in_room, last_changed) VALUES (?, ?, ?)",
                           (uuid, in_room, datetime.datetime.now().timestamp()))
            self.database.commit()
        else:
            cursor.execute("UPDATE bluetooth_occupancy SET in_room=?, last_changed=? WHERE uuid=?",
                           (in_room, datetime.datetime.now().timestamp(), uuid))
            self.database.commit()

    def get_occupancy(self):
        cursor = self.database.cursor()
        cursor.execute("SELECT * FROM bluetooth_occupancy")
        occupancy = cursor.fetchall()
        cursor.close()
        # Get the names of the devices and make this a dictionary
        cursor = self.database.cursor()
        cursor.execute("SELECT * FROM bluetooth_targets")
        targets = cursor.fetchall()
        cursor.close()
        # Make a dictionary of the targets
        targets = {x[1]: x[2] for x in targets}
        # Make a dictionary of the occupancy
        occupancy = {targets[x[0]]: x[1] for x in occupancy}
        return occupancy

    def is_occupied(self):
        return any([x[1] for x in self.get_occupancy()])
