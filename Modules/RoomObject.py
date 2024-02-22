from loguru import logger as logging


class RoomObject:
    object_type = "RoomObject"
    is_promise = True
    is_sensor_only = False  # Indicates that this object is only a sensor and does not have any control capabilities
    is_satellite = False  # Indicates that this object comes from a different controller

    def __init__(self, device_name, device_type):
        self.object_name = device_name
        self.object_type = device_type

        # The following are only implemented on objects that implement this new system of RoomObject
        self._callbacks = []
        self._values = {}
        self._health = {}


    def name(self):
        return self.object_name or self.object_type

    # def get_type(self):
    #     return self.object_type

    def __getattr__(self, item):
        # Check if the attribute is a method and return a dummy method if it is otherwise return None
        # logging.warning(f"Attribute {item} not found in {self.object_name} of type {self.object_type}")

        def method(*args, **kwargs):
            return None

        return method

    def update(self, data):
        """
        Update the object with new data
        """
        self._health = data["health"]
        for key, value in data["data"].items():
            if self._values.get(key, None) != value:
                self.emit_event(f"on_{key}_update", value)
            self._values[key] = value

    def get_values(self):
        return self._values

    def get_value(self, key):
        return self._values.get(key, None)

    def attach_event_callback(self, callback, event_name):
        """
        Attach a callback to an event that this object can emit
        :param callback: The callback function to call
        :param event_name: The name of the event to attach to (e.g. "on_motion")
        """
        self._callbacks.append((callback, event_name))

    def emit_event(self, event_name, *args, **kwargs):
        """
        Emit an event to all attached callbacks
        :param event_name: The name of the event to emit
        :param args: Any arguments to pass to the callback
        :param kwargs: Any keyword arguments to pass to the callback
        """
        for callback, name in self._callbacks:
            if name == event_name:
                callback(*args, **kwargs)

    def __str__(self):
        return f"{self.object_name}={self.object_type}"

    def __repr__(self):
        return f"{self.object_name}={self.object_type}"
