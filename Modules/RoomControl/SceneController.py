import logging

from Modules.RoomControl.API.datagrams import APIMessageRX

logging = logging.getLogger(__name__)


class SceneController:

    def __init__(self, database, room_controllers):
        logging.info("Initializing SceneController instance")
        self.database = database
        self._init_database()

        self.room_controllers = room_controllers
        self.devices = []  # Get all devices from the room controllers

        for controller in self.room_controllers:
            self.devices.extend(controller.get_all_devices())

        self.scenes = {}  # type: dict[str, dict, bool]
        self._load_scenes()

    def _init_database(self):
        cursor = self.database.cursor()
        cursor.execute('''CREATE TABLE IF NOT EXISTS scenes (scene_id TEXT, scene_name TEXT, scene_data TEXT, active BOOLEAN)''')
        self.database.commit()

    def _load_scenes(self):
        cursor = self.database.cursor()
        cursor.execute("SELECT * FROM scenes")
        scenes = cursor.fetchall()
        cursor.close()
        for scene in scenes:
            self.scenes[scene[0]] = {
                "name": scene[1],
                "data": scene[2],
                "active": True if scene[3] == 1 else False
            }

    def get_scenes(self):
        return self.scenes

    def execute_scene(self, scene_id):
        if scene_id not in self.scenes:
            logging.error("Scene {} does not exist".format(scene_id))
            return False
        scene_data = self.scenes[scene_id]["data"]
        command = APIMessageRX(scene_data)
        logging.info("Executing scene {}".format(scene_id))

        for device in self.devices:

            if hasattr(command, device.name()):
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

        # Set the scene to active in the database and all other scenes to inactive
        cursor = self.database.cursor()
        cursor.execute("UPDATE scenes SET active=0")
        cursor.execute("UPDATE scenes SET active=1 WHERE scene_id=?", (scene_id,))
        self.database.commit()
