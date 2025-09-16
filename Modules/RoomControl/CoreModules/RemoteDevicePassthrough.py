import time
from loguru import logger as logging
from Modules.RoomModule import RoomModule

from Modules.RoomControl.CoreModules.Decorators import background


class RemoteDevicePassthrough(RoomModule):

    def __init__(self, room_controller):
        super().__init__(room_controller)
        self.room_controller = room_controller
        self.database = room_controller.database

        self.radiator_temp_sensor = self.room_controller.get_object("RadiatorSensor")
        self.radiator = self.room_controller.get_object("Radiator")
        self.pass_temp()

    @background
    def pass_temp(self):
        logging.info("Starting radiator temp pass through")
        while True:
            temp = self.radiator_temp_sensor.get_value('temperature')
            self.radiator.emit_event('radiator_temp_update', temp)
            time.sleep(15)
