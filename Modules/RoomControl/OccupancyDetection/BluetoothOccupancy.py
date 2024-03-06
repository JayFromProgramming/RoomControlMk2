import datetime
import json
import os
import sqlite3
import sys
import time

import psutil
from loguru import logger as logging

from Modules.RoomControl.Decorators import background
from Modules.RoomModule import RoomModule
from Modules.RoomObject import RoomObject

try:
    import bluetooth
except ImportError:
    logging.error("Bluetooth not available")
    bluetooth = None

try:
    import bluepy.btle as bluetoothLE
except ImportError:
    logging.error("Bluetooth LE not available")
    bluetoothLE = None


class BluetoothDetector(RoomModule):

    def __init__(self, room_controller):
        super().__init__(room_controller)
        self.room_controller = room_controller
        blue_stalker = BlueStalker(self.room_controller.database)

        self.room_controller.attach_object(blue_stalker)


class BlueStalker(RoomObject):
    object_type = "BlueStalker"

    def __init__(self, database: sqlite3.Connection, high_frequency_scan_enabled: bool = False):
        # Target file is a json file that contains bluetooth addresses, name, and role
        super().__init__("BlueStalker", "BlueStalker")
        self.database = database
        self.init_database()

        self.sockets = {}
        self.high_frequency_scan_enabled = high_frequency_scan_enabled

        self.last_checkup = 0
        self.last_scan = 0
        self.scanning = False

        self.enabled = True
        self.scan_lockout_time = 0

        self.reboot_locked_out = False
        self.reboot_timer = None

        self.route_lost = False

        self.set_value("occupants", [])
        self.set_value("targets", {
            uuid: {"address": address, "name": name, "role": role}
            for uuid, address, name, role in self.get_targets()
        })
        self.set_value("occupied", None)
        self.occupant_info = {}
        self.target_mac_addresses = [target["address"] for target in self.get_targets()]

        if bluetooth is None or bluetoothLE is None:
            self.reboot_locked_out = True

        # self.heartbeat_device = "38:1D:D9:F7:6D:44"
        # self.heartbeat_alive = False  # If the heartbeat device is alive

        if bluetooth is not None:
            self.online = True
            self.fault = False
            self.fault_message = ""
        else:
            self.online = True
            self.fault = False
            self.fault_message = "Bluetooth not available"

        self.refresh()

    # def auto_reboot_check(self):
    #     if sys.platform != "linux":
    #         return
    #     # Called only when the bluetooth detector is not functioning
    #     psutil_uptime = time.time() - psutil.boot_time()
    #     # If the pi has been up for less than 5 minutes but not more than 10 minutes
    #     # Then we don't trigger a reboot_lockout because it is likely that initialization is still happening
    #     if 300 > psutil_uptime > 600:
    #         return
    #     elif 600 > psutil_uptime > 3600:
    #         # If the pi has not been up for more than 1 hour and bluetooth is still not working then
    #         # is not likely to fix the problem, and we should not reboot to avoid a reboot loop
    #         self.reboot_locked_out = True
    #         logging.warning("BlueStalker: Failed startup precheck, auto reboot locked out")
    #         return
    #     elif psutil_uptime > 3600:
    #         # If bluetooth was working and then stopped working after 1 hour then we should reboot
    #         # to try and fix the problem
    #         if self.reboot_locked_out:
    #             return
    #         elif self.reboot_timer is None:
    #             logging.warning("BlueStalker: Bluetooth failed, rebooting in 5 minutes")
    #             self.reboot_timer = datetime.datetime.now().timestamp() + 300
    #         else:
    #             # Check if the reboot timer has expired
    #             if self.reboot_timer < datetime.datetime.now().timestamp():
    #                 logging.warning("BlueStalker: Rebooting")
    #                 # Run the reboot command with a 1 minute delay to allow the log to be written
    #                 self.reboot_locked_out = True
    #                 # os.system("sudo shutdown -r +1")
    #                 return

    def init_database(self):
        cursor = self.database.cursor()
        cursor.execute("CREATE TABLE IF NOT EXISTS bluetooth_targets"
                       " (uuid integer constraint table_name_pk primary key "
                       "autoincrement, address TEXT UNIQUE, name TEXT, role TEXT)")
        cursor.execute(
            "CREATE TABLE IF NOT EXISTS bluetooth_occupancy (uuid INTEGER UNIQUE, in_room BOOLEAN, last_changed INTEGER)")
        cursor.close()

    def should_scan(self):
        """Called externally to tell that it is time to scan"""
        if not self.enabled:
            return False
        if not self.online:
            logging.warning("Bluetooth is offline, scan request rejected")
            return False
        if self.scan_lockout_time > datetime.datetime.now().timestamp():
            logging.warning("Scan lockout time has not expired, scan request rejected")
            return False
        logging.info("BlueStalker: Scanning on request")
        self.scan()
        self.scan_lockout_time = datetime.datetime.now().timestamp() + 5

    @background
    def life_check(self):
        """Check if connections are alive, but doesn't run connect"""
        if not self.enabled:
            return
        logging.debug("BlueStalker: Starting Life Check")

        # if not self.heartbeat_alive and heartbeat_was_alive:
        #     logging.error("BlueStalker: Heartbeat device lost, delaying next scan")
        #     return
        for target in self.target_mac_addresses:
            if conn := self.sockets.get(target):  # If the socket is already open
                self.conn_is_alive(conn, target)  # Check if the connection is still alive

        self.last_checkup = datetime.datetime.now().timestamp()

    @background
    def scan(self):
        logging.debug("BlueStalker: Scanning for bluetooth devices")

        if self.scanning:
            logging.warning("BlueStalker: Scan already in progress")
            return

        self.scanning = True
        conn_threads = []
        for target in self.target_mac_addresses:
            if self.sockets.get(target) is None:  # If the socket is already open
                conn_threads.append(self.connect(target))  # Else attempt to connect to the device

        for thread in conn_threads:
            thread.join()
        self.scanning = False
        self.last_scan = datetime.datetime.now().timestamp()  # Update the last update time

    def determine_health(self):
        if self.route_lost:
            self.online = False
            self.fault = True
            self.fault_message = "Bluetooth Adapter Offline"
            return

        # if self.heartbeat_alive:
        #     self.online = True
        #     self.fault = False
        #     self.fault_message = ""
        # else:
        #     # If the heartbeat device is not alive and there are no other devices connected
        #     # Then the bluetooth detector is offline
        #     if len(self.sockets) == 0:
        #         self.fault = True
        #         self.online = False
        #         if self.reboot_locked_out:
        #             self.fault_message = "Radio Failure"
        #         else:
        #             self.fault_message = "Radio Unresponsive"
        #         self.auto_reboot_check()
        #     else:
        #         self.fault = True
        #         self.online = True
        #         self.fault_message = "No Heartbeat"

    @background
    def refresh(self):
        logging.debug(
            f"BlueStalker: Refresh loop started, high frequency scan is {'enabled' if self.high_frequency_scan_enabled else 'disabled'}")
        # Check OS, if not linux then return
        if os.name != "posix":
            logging.error("BlueStalker: In devmode, disabling bluetooth")
            self.online = False
            self.fault = True
            self.fault_message = "Wrong OS"
            return
        while True:
            try:
                self.determine_health()
                self.life_check()
                if self.enabled:
                    if self.high_frequency_scan_enabled:
                        if self.last_scan + 30 < datetime.datetime.now().timestamp():
                            self.scan()
                    else:
                        if self.last_scan + 60 < datetime.datetime.now().timestamp():
                            self.scan()
                self.determine_health()
                time.sleep(15)
            except Exception as e:
                logging.error(f"BluetoothOccupancy: Refresh loop failed with error {e}")
                break
        self.fault = True
        self.fault_message = "Refresh loop exited"

    @background
    def connect(self, address):
        if bluetooth is None:
            self.fault = True
            self.fault_message = "Bluetooth not available"
            return
        sock = bluetooth.BluetoothSocket(bluetooth.RFCOMM)
        sock.setblocking(True)  # Set the socket to non-blocking
        try:
            logging.debug(f"BlueStalker: Connecting to {address}, timeout {sock.gettimeout()}")
            sock.connect((address, 1))  # Start the connection (Will fail with EINPROGRESS)
        except bluetooth.btcommon.BluetoothError as e:
            if e.__str__() == "[Errno 111] Connection refused":  # Connection refused still counts as a connection as
                # the device had to be in range to refuse the connection
                logging.error(f"BlueStalker: Connection to address {address} refused, device is in range")
                self.update_occupancy(address, True)
                return
            elif e.__str__() == "[Errno 115] Operation now in progress":  # This is the error we expect to see
                logging.debug(f"BlueStalker: Connection to {address} is in progress")
                self.update_occupancy(address, False)
                self.sockets[address] = sock  # Add the socket to the list of sockets
                time.sleep(2.5)  # Wait for the connection to complete
                self.conn_is_alive(sock, address)  # Check if the connection is still alive
                return
            elif e.__str__() == "[Errno 113] No route to host":
                # Happens when the Bluetooth adapter is not available
                logging.error(f"BlueStalker: No route to host, bluetooth offline")
                self.route_lost = True
                return
            else:  # Any other error is unexpected
                logging.error(f"BlueStalker: Connection to address {address} failed with error {e}")
                self.update_occupancy(address, False)
                return
        except OSError as e:  # Any additional errors that the OS throws are caught here
            logging.error(f"BlueStalker: Failed to connect to {address} with error {e}")
            self.update_occupancy(address, False)
            return
        else:
            logging.debug(f"BlueStalker: Connected to {address}")
            self.sockets[address] = sock
            self.route_lost = False
            self.update_occupancy(address, True)

    @background
    def conn_is_alive(self, connection, address):
        logging.debug(f"BlueStalker: Checking if {address} is alive")
        try:
            connection.getpeername()
        except bluetooth.BluetoothError as e:
            logging.debug(f"BlueStalker: Connection to {address} is dead, reason: {e}")
            self.update_occupancy(address, False)
            self.sockets.pop(address)
        except OSError as e:
            logging.debug(f"BlueStalker: Connection to {address} is dead, reason: {e}")
            connection.close()
            self.update_occupancy(address, False)
            self.sockets.pop(address)
        else:
            # logging.info(f"Connection to {address} is alive")
            self.update_occupancy(address, True)

    def update_occupancy(self, address, in_room):
        # Get the UUID of the mac address
        cursor = self.database.cursor()
        cursor.execute("SELECT uuid FROM bluetooth_targets WHERE address=?", (address,))
        uuid = cursor.fetchone()[0]
        cursor.close()
        if uuid == 0:
            logging.error(f"Failed to get UUID for {address}")
            return

        self.occupant_info.update({uuid: {"name": self.get_name(uuid), "present": in_room,
                                          "last_changed": datetime.datetime.now().timestamp()}})
        self.set_value("occupants", self.occupant_info)

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
        if not self.enabled:
            return False
        for device in occupancy:
            if device[1] == 1:
                return True
        return False

    def get_targets(self):
        # Return a list of uuids
        cursor = self.database.cursor()
        cursor.execute("SELECT * FROM bluetooth_targets")
        targets = cursor.fetchall()
        cursor.close()
        results = []
        for target in targets:
            results.append({"uuid": target[0], "address": target[1], "name": target[2], "role": target[3]})
        return results

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
        if not self.enabled:
            return False
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
        return self.get_values()

    def get_info(self):
        return {
            "last_scan": self.last_scan,
            "last_check": self.last_checkup
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
