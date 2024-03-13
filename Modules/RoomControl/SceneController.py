import time
import datetime

import ConcurrentDatabase
from Modules.RoomControl.API.datagrams import APIMessageRX
from Modules.RoomControl.Decorators import background

from loguru import logger as logging

from Modules.RoomModule import RoomModule


class SceneController(RoomModule):

    def __init__(self, room_controller):
        super().__init__(room_controller)
        logging.info("Initializing SceneController instance")
        self.database = room_controller.database
        self._init_database()

        self.room_controller = room_controller

        self.scenes = {}  # type: dict[str, dict, bool]
        self.triggers = {}  # type: dict[str, SceneTrigger]
        self._load_scenes()
        self._load_triggers()

    def _init_database(self):
        # cursor = self.database.cursor()
        #  The scenes table contains the scenes and their associated action data
        # cursor.execute('''CREATE TABLE IF NOT EXISTS scenes (scene_id TEXT UNIQUE PRIMARY KEY, scene_data TEXT)''')
        self.database.create_table("scenes", {"scene_id": "TEXT UNIQUE PRIMARY KEY", "scene_data": "TEXT"})
        # The scene_timer table contains the scene_id and the time it should be executed
        # cursor.execute('''
        #     CREATE TABLE IF NOT EXISTS scene_triggers (scene_id TEXT REFERENCES scenes(scene_id) NOT NULL,
        #     trigger_id TEXT UNIQUE PRIMARY KEY NOT NULL,
        #     trigger_name TEXT NOT NULL, trigger_type TEXT NOT NULL, trigger_value TEXT NULL, active boolean)
        # ''')
        self.database.create_table("scene_triggers", {"scene_id": "TEXT REFERENCES scenes(scene_id) NOT NULL",
                                                      "trigger_id": "TEXT UNIQUE PRIMARY KEY NOT NULL",
                                                      "trigger_name": "TEXT NOT NULL",
                                                      "trigger_type": "TEXT NOT NULL",
                                                      "trigger_value": "TEXT NULL",
                                                      "active": "BOOLEAN"})
        # self.database.commit()

    def _load_scenes(self):
        table = self.database.get_table("scenes")
        scenes = table.get_all()
        for scene in scenes:
            self.scenes[scene['scene_id']] = {
                "name": scene['scene_name'],
                "data": scene['scene_data']
            }

    def update_scene(self, scene_id, json_payload):
        """Called by the API to edit a scene"""
        if scene_id not in self.scenes:
            return "Scene does not exist"
        scene = self.scenes[scene_id]
        # The json payload will contain the triggers and the scene data
        triggers = json_payload.get("triggers", [])
        scene_data = json_payload.get("scene_data", "")
        return "Not implemented"

    def delete_scene(self, scene_id):
        """Called by the API to delete a scene"""
        if scene_id not in self.scenes:
            return "Scene does not exist"
        del self.scenes[scene_id]
        # Remove all triggers associated with the scene
        self.database.run("DELETE FROM scene_triggers WHERE scene_id=?", (scene_id,))
        self.database.run("DELETE FROM scenes WHERE scene_id=?", (scene_id,))
        return "Scene deleted"

    def get_scenes(self):
        """Returns a dictionary of all triggers"""
        val = {}
        for trigger_id, trigger in self.triggers.items():
            val[trigger_id] = trigger.api_data()
        return val

    def _load_triggers(self):
        logging.info("SceneController: Loading triggers...")
        table = self.database.get_table("scene_triggers")
        triggers = table.get_all()
        for trigger in triggers:
            self.triggers.update({
                trigger['trigger_id']:
                    SceneTrigger(trigger['scene_id'], trigger['trigger_id'], trigger['trigger_name'],
                                 trigger['trigger_type'], trigger['trigger_value'], trigger['active'],
                                 self.database, self.execute_scene,
                                 self.action_to_str(trigger['scene_id']), self.scenes[trigger['scene_id']]["data"])
            })

    def execute_trigger(self, trigger_id):
        if trigger_id not in self.triggers:
            logging.error("Trigger {} does not exist".format(trigger_id))
            return False
        trigger = self.triggers[trigger_id]
        return trigger.execute_command()

    def execute_scene(self, scene_id):
        if scene_id not in self.scenes:
            logging.error("Scene {} does not exist".format(scene_id))
            return False
        scene_data = self.scenes[scene_id]["data"]
        command = APIMessageRX(scene_data)
        logging.info("Executing scene {}".format(scene_id))

        for device in self.room_controller.room_objects:

            if hasattr(command, device.object_name):
                logging.info(f"Executing scene command for device {device.name()}")
                device_command = getattr(command, device.name())
                for action, value in device_command.items():
                    if action == "on" and hasattr(device, "on"):
                        device.on = value
                    if action == "brightness" and hasattr(device, "brightness"):
                        device.brightness = value
                    if action == "color" and hasattr(device, "color"):
                        device.color = value
                    if action == "white" and hasattr(device, "white"):
                        device.white = value
                    if action == "target_value" and hasattr(device, "setpoint"):
                        device.setpoint = value
                    if action == "enable_dnd" and hasattr(device, "enable_dnd"):
                        device.enable_dnd = value

    def action_to_str(self, scene_id):
        """
        Returns human readable discription of the actions of the scene
        Example: Sets [device] [setting] to [value]
        """
        actions = []
        if scene_id not in self.scenes:
            logging.error("Scene {} does not exist".format(scene_id))
            return f"Scene {scene_id} does not exist"
        scene_data = self.scenes[scene_id]["data"]
        command = APIMessageRX(scene_data)
        for device in self.room_controller.room_objects:
            if hasattr(command, device.object_name):
                device_command = getattr(command, device.name())
                for action, value in device_command.items():
                    if action == "on":
                        actions.append("{name} {value}".format(name=f"[{device.name()}]",
                                                               value='on' if value else 'off'))
                    elif action == "brightness":
                        actions.append("{name} brightness {value}".format(name=f"[{device.name()}]",
                                                                          value=value))
                    elif action == "color":
                        r, g, b = value
                        color = f"({r}, {g}, {b})"
                        actions.append("{name} color to {value}".format(name=f"[{device.name()}]", value=color))
                    elif action == "white":
                        actions.append("{name} white to {value}".format(name=f"[{device.name()}]", value=value))
                    elif action == "target_value":
                        actions.append("{name} setpoint to {value}".format(name=f"[{device.name()}]", value=value))
                    elif action == "enable_dnd":
                        actions.append("{name} DND {value}".format(name=f"[{device.name()}]",
                                                                   value='on' if value else 'off'))
                    else:
                        actions.append("Preforms unknown action {action} on {name}".format(action=action,
                                                                                           name=f"[{device.name()}]"))

        return ", ".join(actions)


class SceneTrigger:

    def __init__(self, scene_id, trigger_id, trigger_name, trigger_type,
                 trigger_value, active, database: ConcurrentDatabase.Database, callback, action_string,
                 data):
        self.scene_id = scene_id
        self.trigger_id = trigger_id
        self.trigger_name = trigger_name
        self.trigger_type = trigger_type
        self.trigger_value = trigger_value
        self.data = data
        self.active = False if active == 0 else True
        self.database = database
        self.callback = callback

        self.action_string = action_string

        logging.info(f"Initializing SceneTrigger ({self.trigger_name})")
        self.api_action = None
        self.prime()

    def prime(self):
        """When called this will cause the scene trigger to prepare either a timer or a sensor trigger"""
        match self.trigger_type:
            case "weekly":
                self._prep_interval_trigger(self.trigger_type, self.trigger_value)
                self.api_action = "arm/disarm"
            case "daily":
                self._prep_interval_trigger(self.trigger_type, self.trigger_value)
                self.api_action = "arm/disarm"
            case "hourly":
                self._prep_interval_trigger(self.trigger_type, self.trigger_value)
                self.api_action = "arm/disarm"
            case "immediate":
                self.api_action = "run"
            case _:
                logging.error(f"SceneTrigger ({self.trigger_name}) has an invalid trigger type ({self.trigger_type})")
                return
        logging.info(
            f"SceneTrigger ({self.trigger_name}): Initialized with trigger type {self.trigger_type} and api action {self.api_action}")

    def _prep_interval_trigger(self, interval_type: str, interval_value: str):
        """
        Prepares a timer trigger
        :param interval_type: The type of interval trigger (daily, weekly, hourly)
        :param interval_value: The time of day to trigger the scene either in the format WD*:HH:MM or WD*:HH:MM:SS
        """
        match interval_type:
            case "weekly":
                datetime_format = "%w:%H:%M"
            case "daily":
                datetime_format = "%H:%M"
            case "hourly":
                datetime_format = "%M:%S"
            case _:
                logging.error(f"SceneTrigger ({self.trigger_name}) has an invalid interval type ({interval_type})")
                return

        # Parse the interval value
        try:
            interval_time = datetime.datetime.strptime(interval_value, datetime_format)
            # The interval time will 1900-01-01 plus whatever the interval rate will be so we need to add the current date
            # to the interval time
            interval_time = datetime.datetime.combine(datetime.datetime.now().date(), interval_time.time())

        except ValueError:
            logging.error(f"SceneTrigger ({self.trigger_name}): has an invalid interval value ({interval_value})")
            return

        # Get the current time
        now = datetime.datetime.now()

        # Calculate the time delta between now and the trigger time
        match interval_type:
            case "weekly":
                # If the trigger time is before now then add 7 days to the trigger time
                if interval_time < now:
                    interval_time += datetime.timedelta(days=7)
                # Calculate the time delta
                time_delta = interval_time - now
            case "daily":
                # If the trigger time is before now then add 1 day to the trigger time
                if interval_time < now:
                    interval_time += datetime.timedelta(days=1)
                # Calculate the time delta
                time_delta = interval_time - now
            case "hourly":
                # If the trigger time is before now then however many hours have gone by today
                interval_time += datetime.timedelta(hours=now.hour)
                if interval_time < now:
                    interval_time += datetime.timedelta(hours=1)
                # Calculate the time delta
                time_delta = interval_time - now
            case _:
                time_delta = 0
                logging.error(f"SceneTrigger ({self.trigger_name}) has an invalid interval type ({interval_type})")

        # Create the timer
        logging.info(f"SceneTrigger ({self.trigger_name}): will trigger at {interval_time}")
        self._timer_trigger(time_delta.total_seconds())

    @background
    def _timer_trigger(self, execution_delay):
        """Executes the scene after the specified delay"""
        logging.info(f"SceneTrigger ({self.trigger_name}): Trigger primed, will execute in {execution_delay} seconds")
        time.sleep(execution_delay)
        self.execute()
        # Re-prime the trigger after it has executed
        self.prime()

    def execute_command(self):
        match self.api_action:
            case "arm/disarm":
                self.toggle_active()
                return True
            case "run":
                self.execute()
                return True
            case _:
                logging.error(f"SceneTrigger ({self.trigger_name}): Invalid api action ({self.api_action})")
                return False

    def toggle_active(self):
        # self.active = not self.active
        # cursor = self.database.cursor()
        # cursor.execute("UPDATE scene_triggers SET active=? WHERE trigger_id=?", (self.active, self.trigger_id))
        # self.database.commit()
        self.active = not self.active
        logging.info(f"SceneTrigger ({self.trigger_name}): Toggled active to {self.active}")

        self.database.run("UPDATE scene_triggers SET active=? WHERE trigger_id=?",
                          (0 if self.active is False else 1, self.trigger_id))

        # table = self.database.get_table("scene_triggers")
        # row = table.get_row(trigger_id=self.trigger_id)
        # row.active = self.active

    def execute(self):
        """Executes the scene associated with this trigger"""
        if self.active or self.trigger_type == "immediate":
            self.callback(self.scene_id)
        else:
            logging.info(f"SceneTrigger ({self.trigger_name}): not executing because it is not active")

    def api_data(self) -> dict:
        """Returns a dictionary of data that can be used to populate an API response"""
        return {
            "scene_id": self.scene_id,
            "trigger_id": self.trigger_id,
            "trigger_name": self.trigger_name,
            "trigger_type": self.trigger_type,
            "trigger_value": self.trigger_value,
            "active": self.active if self.trigger_type != "immediate" else False,
            "action": self.action_string,
            "api_action": self.data
        }
