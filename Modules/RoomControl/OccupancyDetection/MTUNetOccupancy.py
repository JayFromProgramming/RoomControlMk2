import datetime
import os
import sqlite3
import time

from Modules.RoomControl.AbstractSmartDevices import background
import logging
import subprocess

logging = logging.getLogger(__name__)


def ping(ip_address, count=4, timeout=1) -> (float, float):
    if os.name == "nt":
        command = f"ping -n {count} -w {timeout * 1000} {ip_address}"
    else:
        command = f"ping -c {count} -W {timeout} {ip_address}"

    logging.info(f"Running command: {command}")

    result = subprocess.run(command, shell=True, capture_output=True)

    # Get the average time and the packet loss
    output = result.stdout.decode("utf-8")
    logging.info(f"Output: {output}")

    # Get the average time
    try:
        if os.name == "nt":
            average_time = output.split("Average = ")[1].split("ms")[0]
            # Get the packet loss
            packet_loss = float(output.split("Lost = ")[1].split("(")[0]) / count
        else:
            average_time = output.split("avg = ")[1].split("ms")[0]
            # Get the packet loss
            packet_loss = output.split("loss = ")[1].split("%")[0]
    except IndexError:
        logging.info("Failed to get the average time or packet loss")
        return None, 1
    return float(average_time), float(packet_loss)


class Device:

    def __init__(self, name: str, database: sqlite3.Connection):
        self.name = name
        self.database = database
        self.entry = self.database.run("SELECT * FROM network_occupancy WHERE name=?", (name,))
        self.entry = self.entry.fetchone()

        # Database values
        self.on_campus = self.entry[1]
        self.last_seen = datetime.datetime.fromtimestamp(self.entry[2])
        self.ip_address = self.entry[3]
        self.last_ip_update = datetime.datetime.fromtimestamp(self.entry[4])

        # Other values
        self.bad_ip = False
        self.missed_pings = 0

    def _validate_ip(self):
        # The subnet is 141.219.x.x
        return self.ip_address.startswith("141.219.")

    def get_name(self):
        return self.name

    def get_ip(self):
        return self.ip_address

    def get_last_ip_update(self):
        return self.last_ip_update

    def get_last_seen(self):
        return self.last_seen

    def on_campus(self):
        return self.on_campus

    def ping(self):
        # Pings the device and returns True if the ping was successful
        try:
            logging.info(f"Pinging {self.name}")
            timeout = 1
            response = ping(self.ip_address, timeout=timeout, count=4)
            if response[1] == 0:
                logging.info(f"Ping successful for {self.name}, RTT: {response[0]}")
                self.missed_pings = 0
                self.last_seen = datetime.datetime.now()
                self.on_campus = True
                return True
            else:
                packet_loss = response[1]
                self.missed_pings += 1
                logging.info(f"Ping unsuccessful for {self.name}, packet loss: {packet_loss}, missed pings: {self.missed_pings}")
                if self.missed_pings > 4:
                    self.on_campus = False
                    self.missed_pings = 0
                return False
        except Exception as e:
            logging.error(f"Error pinging {self.name}: {e}")
            return False

    def needs_ping(self):
        # Returns True if the device needs to be pinged
        if self.on_campus:
            if datetime.datetime.now() - self.last_seen > datetime.timedelta(minutes=2):
                return True
            elif self.missed_pings > 0:
                return True
            else:
                return False
        else:
            if datetime.datetime.now() - self.last_seen > datetime.timedelta(minutes=1):
                return True
            else:
                return False

    def update_db(self):
        # Updates the database with the current values
        self.database.run("UPDATE network_occupancy SET on_campus=?, last_seen=? WHERE name=?",
                          (self.on_campus, self.last_seen.timestamp(), self.name))

    def fetch_ip(self):
        # The device ip is updated by the device in the database, so periodically fetch the ip from the database
        if datetime.datetime.now() - self.last_ip_update > datetime.timedelta(minutes=5):
            values = self.database.run("SELECT ip_address, last_ip_update FROM network_occupancy WHERE name=?", (self.name,))
            self.ip_address = values[0]
            self.last_ip_update = datetime.datetime.fromtimestamp(values[1])


class NetworkOccupancyDetector:
    """
    Pings devices to see if they are on campus, and updates the database accordingly
    Devices that are believed to be on campus are pinged 2 minutes
    If a device misses a ping then it is pinged 4 times in 15 second intervals and if it misses
     all 4 then it is assumed to be off campus and the database is updated
    Devices that are believed to be off campus are pinged every minute
    """

    def __init__(self, database: sqlite3.Connection):
        self.database = database
        self.init_database()
        self.devices = []
        self.load_devices()
        self.net_detect_periodic_refresh()

    def init_database(self):
        self.database.run(
            "CREATE TABLE IF NOT EXISTS network_occupancy (name TEXT, on_campus BOOLEAN, last_seen INTEGER, "
            "ip_address TEXT, last_ip_update INTEGER)")

    def load_devices(self):
        cursor = self.database.cursor()
        cursor.execute("SELECT * FROM network_occupancy")
        rows = cursor.fetchall()
        for row in rows:
            self.devices.append(Device(row[0], self.database))

    def valid_ip(self, ip: str):
        # Checks if the IP address is a valid MTU IP address (subnet 141.219.x.x)
        return ip.startswith("141.219.")

    def is_on_campus(self, name: str):
        # Returns True if the device is on campus
        for device in self.devices:
            if device.get_name() == name:
                return device.on_campus
        return False

    @background
    def net_detect_periodic_refresh(self):
        logging.info("Starting periodic refresh")
        while True:
            try:
                for device in self.devices:
                    if device.needs_ping():
                        device.ping()
                        device.update_db()
            except Exception as e:
                logging.error(f"Error in periodic refresh: {e}")
            finally:
                time.sleep(15)  # Sleep for 15 seconds
