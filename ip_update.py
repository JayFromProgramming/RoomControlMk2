import datetime
import sqlite3
import argparse


# This python program is called remotely over SSH by a phone to allow it to update its ip address in the database

def main():
    parser = argparse.ArgumentParser(description="Update the ip address of a device in the database")
    parser.add_argument("device", help="The name of the device to update")
    parser.add_argument("ip", help="The ip address of the device")
    args = parser.parse_args()

    database = sqlite3.connect("room_data.db", check_same_thread=True)
    cursor = database.cursor()

    cursor.execute("UPDATE network_occupancy SET ip_address = ?, last_ip_update = ? WHERE name = ?",
                   (args.ip, datetime.datetime.now().timestamp(), args.device))

    database.commit()
    database.close()


if __name__ == "__main__":

    # Make sure the working directory is the same as the location of this file
    import os
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    try:
        main()
    except Exception as e:
        print(f"Failing with error: {e}")
