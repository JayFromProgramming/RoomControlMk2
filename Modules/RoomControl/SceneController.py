import time
import datetime

import ConcurrentDatabase
from Modules.RoomControl.API.datagrams import APIMessageRX
from Modules.RoomControl.Decorators import background

from loguru import logger as logging

from Modules.RoomControl.SceneTriggerTypes.IntervalTrigger import IntervalTrigger
from Modules.RoomControl.SceneTriggerTypes.SceneTrigger import SceneTrigger
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
        self.trigger_tasks = []
        self._load_scenes()
        self._load_triggers()

    def _init_database(self):
        self.database.create_table("scenes", {"scene_id": "TEXT UNIQUE PRIMARY KEY", "scene_name": "TEXT NOT NULL",
                                              "scene_data": "TEXT"})
        self.database.create_table("scene_triggers", {"scene_id": "TEXT REFERENCES scenes(scene_id) NOT NULL",
                                                      "trigger_id": "TEXT UNIQUE PRIMARY KEY NOT NULL",
                                                      "trigger_name": "TEXT NOT NULL",
                                                      "trigger_type": "TEXT NOT NULL",
                                                      "trigger_value": "TEXT NULL",
                                                      "active": "BOOLEAN"})
        self.database.update_table("scene_triggers", 1, [
            "DROP TABLE scene_triggers;",
            "CREATE TABLE scene_triggers (scene_id TEXT REFERENCES scenes(scene_id) NOT NULL,"
            "trigger_id SERIAL PRIMARY KEY NOT NULL,"
            "trigger_type TEXT NOT NULL,"
            "trigger_subtype TEXT NOT NULL,"
            "trigger_value TEXT NULL, "
            "active BOOLEAN);"
        ])

        # self.database.commit()

    def _load_scenes(self):
        for scene in self.scenes:
            del scene
        self.scenes = {}
        table = self.database.run("SELECT * FROM scenes")
        scenes = table.fetchall()
        for scene in scenes:
            self.scenes[scene[0]] = {
                "name": scene[1],
                "data": scene[2]
            }

    def _update_triggers(self, scene_id, triggers):
        db_triggers = self.database.run("SELECT * FROM scene_triggers WHERE scene_id=?", (scene_id,))
        db_triggers = db_triggers.fetchall()
        for db_trigger in db_triggers:
            if db_trigger[1] not in [trigger["trigger_id"] for trigger in triggers]:
                logging.info(f"Deleting trigger {db_trigger[1]} from scene {scene_id}")
                # Delete the trigger
                self.database.run("DELETE FROM scene_triggers WHERE trigger_id=?", (db_trigger[1],))
        for trigger in triggers:
            if trigger["trigger_id"] == "0":
                logging.info(f"Adding new trigger to scene {scene_id}")
                # Calculate the next trigger_id
                new_id = self.database.run("SELECT MAX(trigger_id) FROM scene_triggers").fetchone()[0]
                if new_id is None:
                    new_id = 1
                else:
                    new_id += 1
                # Add a new trigger
                self.database.run("INSERT INTO scene_triggers "
                                  "(scene_id, trigger_id, trigger_type, trigger_subtype, "
                                  "trigger_value, active) VALUES (?, ?, ?, ?, ?, ?)",
                                  (scene_id, new_id,
                                   trigger["trigger_type"], trigger["trigger_subtype"],
                                   trigger["trigger_value"], trigger["enabled"]))
            else:
                # Update the trigger
                logging.info(f"Updating trigger {trigger['trigger_id']} for scene {scene_id}")
                self.database.run("UPDATE scene_triggers SET trigger_type=?, trigger_subtype=?, trigger_value=?, "
                                  "active=? WHERE trigger_id=?",
                                  (trigger["trigger_type"], trigger["trigger_subtype"], trigger["trigger_value"],
                                   trigger["enabled"], trigger["trigger_id"]))

    def update_scene(self, scene_id, json_payload):
        """Called by the API to edit a scene"""
        try:
            if scene_id not in self.scenes:
                return "Scene does not exist"
            scene = self.scenes[scene_id]
            # The json payload will contain the triggers and the scene data
            triggers = json_payload.get("triggers", [])  # implement later
            scene_data = json_payload.get("scene_data", "")
            scene_data = APIMessageRX(scene_data).__str__()
            logging.info(f"Updating scene {scene_id} with data {scene_data}")
            # Update the scene data
            self.database.run("UPDATE scenes SET scene_data=? WHERE scene_id=?", (scene_data, scene_id))
            # Update the triggers
            self._update_triggers(scene_id, triggers)
            # Reload the scenes
            self._load_scenes()
            self._load_triggers()
            return "success"
        except Exception as e:
            logging.error(f"Error updating scene: {e}")
            logging.exception(e)
            return f"{e}"

    def delete_scene(self, scene_id):
        """Called by the API to delete a scene"""
        if scene_id not in self.scenes:
            return "Scene does not exist"
        del self.scenes[scene_id]
        # Remove all triggers associated with the scene
        self.database.run("DELETE FROM scene_triggers WHERE scene_id=?", (scene_id,))
        self.database.run("DELETE FROM scenes WHERE scene_id=?", (scene_id,))
        return "success"

    def get_scenes(self):
        """Returns a dictionary of all scenes, including their triggers"""
        scenes = {}
        for scene_id, scene in self.scenes.items():
            triggers = self.get_triggers(scene_id)
            scenes[scene_id] = {
                "name": scene["name"],
                "data": scene["data"],
                "action": self.action_to_str(scene_id),
                "triggers": triggers
            }
        return scenes

    def get_triggers(self, scene_id):
        """Returns a list of triggers for the specified scene"""
        triggers = []
        for trigger_id, trigger in self.triggers.items():
            if trigger.scene_id == scene_id:
                triggers.append(trigger.info())
        return triggers

    def execute_command(self, command, scene_id, payload):
        match command:
            case "add_scene":
                return self.add_scene(scene_id, payload)
            case "update_scene":
                return self.update_scene(scene_id, payload)
            case "delete_scene":
                return self.delete_scene(scene_id)
            case "execute_scene":
                return self.execute_scene(scene_id)
            case "test_scene":
                return self.run_scene(payload)

    def _load_triggers(self):
        logging.info("SceneController: Loading triggers...")
        for trigger in self.triggers.values():
            trigger.stopped = True
            del trigger
        self.triggers = {}
        table = self.database.run("SELECT * FROM scene_triggers")
        triggers = table.fetchall()
        for trigger in triggers:
            match trigger[2]:
                case "IntervalTrigger":
                    self.triggers[trigger[1]] = IntervalTrigger(self, trigger[0], trigger[1], trigger[3], trigger[4],
                                                                trigger[5])
                case _:
                    logging.error(f"Unknown trigger type {trigger[2]}")
        for trigger in self.triggers.values():
            trigger.run()

    def execute_scene(self, scene_id):
        if scene_id not in self.scenes:
            logging.error("Scene {} does not exist".format(scene_id))
            return False
        scene_data = self.scenes[scene_id]["data"]
        command = APIMessageRX(scene_data)
        logging.info("Executing scene {}".format(scene_id))
        self.run_scene(command)

    def run_scene(self, command):

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
