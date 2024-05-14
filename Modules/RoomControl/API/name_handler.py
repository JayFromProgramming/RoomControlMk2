from loguru import logger as logging


class NameHandler:

    def __init__(self, room_controller):
        self.room_controller = room_controller
        self.database = room_controller.database
        self.database_init()

    def database_init(self):
        self.database.create_table("name_relations", {"name": "TEXT", "object_id": "TEXT"})

    def get_name(self, object_id):
        row = self.database.get_table("name_relations").get_row(object_id=object_id)
        if row:
            return row['name']
        # logging.warning(f"{object_id} did not have a front facing name in name_relations")
        return object_id

    def set_name(self, object_id, name):
        self.database.get_table("name_relations").add(name=name, object_id=object_id)
