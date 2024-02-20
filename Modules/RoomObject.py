
class RoomObject:

    object_type = "RoomObject"

    def __init__(self, device_name, device_type):
        self.object_name = device_name
        self.object_type = device_type
        self.is_a_promise = True

    def name(self):
        return self.object_name

    def __str__(self):
        return f"{self.object_name} is a {self.object_type}"

    def __repr__(self):
        return f"|{self.object_name}, {self.object_type}|"
