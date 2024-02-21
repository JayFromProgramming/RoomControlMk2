class PinWatcher(RoomObject):

    is_promise = False
    is_sensor_only = True

    def __init__(self, name, pin, callback: callable, edge=None, bouncetime=200, normally_open=True,
                 enabled=True, database=None):
        super().__init__(name, "PinWatcher")
        self.online = True
        self.fault = False
        self.fault_message = ""
        self.pin = pin  # Pin number
        self.state = None  # None = Unknown, True = On, False = Off
        self._name = name  # Name of the device
        self.enabled = enabled  # Is the device enabled for detection

        self._last_rising = 0  # Last time the device was triggered
        self._last_falling = 0  # Last time the device was triggered

        self.callback = callback
        self.edge = None
        self.bouncetime = bouncetime
        self.normal_open = normally_open
        self.database = database

        if GPIO is None:
            self.fault = True
            self.fault_message = "RPi.GPIO not found"
            logging.warning(f"PinWatcher ({name}): Not initializing, RPi.GPIO not found")
            return

        self.edge = edge if edge is not None else GPIO.BOTH
        try:
            GPIO.setup(self.pin, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
            self.state = GPIO.input(self.pin) if self.normal_open else not GPIO.input(self.pin)
            GPIO.add_event_detect(self.pin, self.edge, callback=self._callback, bouncetime=self.bouncetime)
            logging.debug(f"PinWatcher ({name}): Initialized")
        except Exception as e:
            self.fault = True
            self.fault_message = str(e)
            logging.warning(f"PinWatcher ({name}): Error initializing: {e}")

    def _callback(self, pin):
        self.state = GPIO.input(self.pin) if self.normal_open else not GPIO.input(self.pin)

        if self.state:  # If the device is active
            self._last_rising = time.time()
        else:
            self._last_falling = time.time()

        logging.debug(f"PinWatcher ({self.name()}): Pin {pin} changed state to {self.state}")
        self.callback(pin)
        # Setup new event detect
        GPIO.remove_event_detect(self.pin)
        GPIO.add_event_detect(self.pin, self.edge, callback=self._callback, bouncetime=self.bouncetime)

    def name(self):
        return self._name

    def get_state(self):
        return {
            "on": self.enabled,
            "triggered": self.state,
            "active_for": 0 if not self.state else time.time() - self._last_rising,
            "last_active": self._last_rising,
        }

    def get_info(self):
        return {
            "name": self.name(),
            "pin": self.pin,
            "edge": self.edge,
            "bouncetime": self.bouncetime
        }

    def get_type(self):
        return "pin_watcher"

    def get_health(self):
        return {
            "online": True,
            "fault": self.fault,
            "reason": self.fault_message
        }

    def auto_state(self):
        return False

    @property
    def on(self):
        return self.enabled

    @on.setter
    def on(self, value):
        self.database.run("UPDATE occupancy_sources SET enabled = ? WHERE name = ?", (value, self.name()), commit=True)
        self.enabled = value