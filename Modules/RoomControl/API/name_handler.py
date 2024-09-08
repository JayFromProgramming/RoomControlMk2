from loguru import logger as logging


class NameHandler:

    def __init__(self, room_controller):
        self.room_controller = room_controller
        self.database = room_controller.database
        self.database_init()

    def database_init(self):
        self.database.create_table("name_relations", {"name": "TEXT", "object_id": "TEXT"})

    def get_name(self, object_id):
        row = self.database.run("SELECT * FROM name_relations WHERE object_id = ?", (object_id,)).fetchone()
        if row:
            return row[0]
        # logging.warning(f"{object_id} did not have a front facing name in name_relations")
        return f"|{object_id}|"

    def set_name(self, object_id, name):
        current_name = self.get_name(object_id).strip('|')
        if current_name == object_id:
            logging.info(f"Adding {object_id} name {name}")
            self.database.run("INSERT INTO name_relations (name, object_id) VALUES (?, ?)", (name, object_id))
        else:
            logging.info(f"Updating {object_id} name from {current_name} to {name}")
            self.database.run("UPDATE name_relations SET name = ? WHERE object_id = ?", (name, object_id))


