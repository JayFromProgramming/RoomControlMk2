

class RoomModule:

    search_name = None
    search_type = None

    def __init__(self, room_controller):
        self.room_controller = room_controller
        self.room_controller.attach_module(self)
