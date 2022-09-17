

class SceneController:

    def __init__(self, database, room_controllers):
        self.database = database
        self.room_controllers = room_controllers
        self.scenes = {}
        self._load_scenes()


    def _load_scenes(self):
        cursor = self.database.cursor()
        cursor.execute("SELECT * FROM scenes")
        scenes = cursor.fetchall()
        cursor.close()
        for scene in scenes:
            pass

    def execute_scene(self, scene_id):
        pass