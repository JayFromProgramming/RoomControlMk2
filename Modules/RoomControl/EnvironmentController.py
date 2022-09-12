import time
import logging

from Modules.RoomControl.AbstractSmartDevices import AbstractToggleDevice, background

logging = logging.getLogger(__name__)


class EnvironmentControllerHost:

    def __init__(self, database, sources=None, room_controllers=None):

        if room_controllers is None:
            room_controllers = []
        if sources is None:
            sources = []

        self.database = database
        self.database_init()
        self.room_controllers = room_controllers
        self.enviv_controllers = {}
        self.sources = sources

        cursor = self.database.cursor()
        cursor.execute("SELECT * FROM enviv_controllers")
        controllers = cursor.fetchall()
        for controller in controllers:
            self.enviv_controllers[controller[0]] = \
                EnvironmentController(controller[0], self.database, room_controllers=self.room_controllers)

    def database_init(self):
        cursor = self.database.cursor()
        cursor.execute("""CREATE TABLE IF NOT EXISTS 
                        enviv_controllers (
                        name text,
                        current_set_point integer,
                        source_name text,
                        enabled boolean
                        )""")
        cursor.execute("""CREATE TABLE IF NOT EXISTS
                        enviv_control_devices (
                        device_id text,
                        lower_delta integer,
                        upper_delta integer,
                        control_source text
                        )""")
        cursor.close()
        self.database.commit()


class EnvironmentController:

    def __init__(self, name, database, room_controllers=None):

        if room_controllers is None:
            room_controllers = []

        self.name = name
        self.database = database
        self.room_controllers = room_controllers

        cursor = self.database.cursor()
        cursor.execute("SELECT * FROM enviv_controllers WHERE name=?", (self.name,))
        controller = cursor.fetchone()
        cursor.close()
        self.current_setpoint = controller[1]
        self.source = controller[2]
        self.enabled = (False if controller[3] == 0 else True)

        self.devices = []
        cursor = self.database.cursor()
        cursor.execute("SELECT * FROM enviv_control_devices WHERE control_source=?", (self.name,))
        devices = cursor.fetchall()
        for device in devices:
            self.devices.append(ControlledDevice(device[0], self.get_device(device[0]), self.database))

        self.periodic_check()

    def get_device(self, device_name):
        for room_controller in self.room_controllers:
            if device := room_controller.get_device(device_name):
                return device
        return None

    @background
    def periodic_check(self):

        if hasattr(self.source, "get_current_value"):
            while True:
                for device in self.devices:
                    device.check(self.source.get_current_value(), self.current_setpoint)
                time.sleep(60)
        else:
            logging.error(f"Source {self.source} does not have a get_current_value method")


class ControlledDevice:

    def __init__(self, name, device: AbstractToggleDevice, database):
        self.name = name
        self.device = device
        self.database = database

        cursor = self.database.cursor()
        cursor.execute("SELECT * FROM enviv_control_devices WHERE device_id=?", (self.name,))
        device = cursor.fetchone()
        cursor.close()
        self.control_source = device[1]
        self.lower_hysteresis = device[2]
        self.upper_hysteresis = device[3]

    """
    Checks if this particular device should be on or off 
    """

    def check(self, current_value, setpoint):
        if current_value > setpoint + self.upper_hysteresis:
            self.device.set_on(False)
        elif current_value < setpoint - self.lower_hysteresis:
            self.device.set_on(True)
