
class RoomObject:

    object_type = "RoomObject"
    is_promise = True

    def __init__(self, device_name, device_type):
        self.object_name = device_name
        self.object_type = device_type

    def name(self):
        return self.object_name or self.object_type

    # def get_type(self):
    #     return self.object_type

    def __getattr__(self, item):
        # Check if the attribute is a method and return a dummy method if it is otherwise return None
        def method(*args, **kwargs):
            return None
        return method

    def __str__(self):
        return f"{self.object_name}={self.object_type}"

    def __repr__(self):
        return f"{self.object_name}={self.object_type}"
