import json

from loguru import logger as logging
from aiohttp import web

from Modules.APIModule import APIModule


class SchemaBuilder(APIModule):

    def __init__(self, room_controller):
        super().__init__()
        self.room_controller = room_controller
        self.database = room_controller.database
        self.init_database()
        self.import_from_old_schema("testing")

    def get_routes(self):
        return [web.get('/get_schema', self.handle_get_schema)]

    def init_database(self):
        self.database.create_table("interface_schemas_devices", {
            "interface_name": "TEXT",
            "device_name": "TEXT",
            "device_starred": "BOOLEAN",
            "device_priority": "INTEGER",
            "device_group": "INTEGER"
        }, primary_keys=["interface_name", "device_name"])

        self.database.create_table("interface_schemas_groups", {
            "group_id": "INTEGER",
            "group_name": "TEXT",
            "group_priority": "INTEGER"
        }, primary_keys=["group_id"])

    def get_all_devices(self):
        """Gets every device from the room controller which is the default set of devices if an interface has no saved schema"""
        devices = {}
        for obj in self.room_controller.get_all_objects():
            devices[obj.name()] = {
                "group": None,
                "starred": False
            }
        return devices

    def make_default_schema(self, devices):
        schema = {}
        for device_name in devices:
            schema[device_name] = {
                "group": None,
                "starred": False
            }
        return schema

    def import_from_old_schema(self, target_interface):
        logging.info("Checking if target schema has already been imported")
        # Check if the schema already exists in the database
        schema_devices_table = self.database.get_table("interface_schemas_devices")
        existing_schema = schema_devices_table.get_rows(interface_name=target_interface)
        if existing_schema:
            logging.info(f"Schema for interface {target_interface} already exists, skipping import")
            return
        logging.info(f"Importing old schema for interface {target_interface}")
        with open("Modules/RoomControl/Configs/new_schema.json", "r") as f:
            old_schema = json.load(f)

        group_number = 1
        for device_name, device_info in old_schema.items():
            # Check if the group already exists
            group_table = self.database.get_table("interface_schemas_groups")
            if device_info["group"] is not None:
                existing_group = group_table.get_row(group_name=device_info["group"])
                if existing_group:
                    group_id = existing_group["group_id"]
                else:
                    # Create a new group
                    group_entry = group_table.add(group_name=device_info["group"], group_priority=group_number)
                    group_id = group_entry["group_id"]
                    group_number += 1
            else:
                group_id = None

            # Insert the device into the devices table
            device_table = self.database.get_table("interface_schemas_devices")
            try:
                device_table.add(interface_name=target_interface,
                                 device_name=device_name,
                                 device_starred=device_info["starred"],
                                 device_priority=device_info.get("priority", None),
                                 device_group=group_id)
            except AttributeError:
                pass
        logging.info("Finished importing old schema for testing")

    def get_group_name(self, group_id):
        group_table = self.database.get_table("interface_schemas_groups")
        group_row = group_table.get_row(group_id=group_id)
        if group_row:
            return group_row["group_name"]
        return None

    async def handle_get_schema(self, request):
        """
        Schema example
        {
        "device_name": {
        "group": "Group Name",
        "starred": true | false,
        "priority": 1 [optional]
        }, ...
        }
        """
        interface_name = request.query.get("interface_name", None)
        add_all = request.query.get("add_all", "false").lower() == "true"
        if interface_name is None:
            logging.error("interface_name query parameter is required")
            return web.json_response({"error": "interface_name query parameter is required"}, status=400)

        # Get the schema devices from the database that match the interface_name
        schema_devices_table = self.database.get_table("interface_schemas_devices")
        schema_devices = schema_devices_table.get_rows(interface_name=interface_name)
        if not schema_devices:
            # If no schema devices are found, return all devices with default values
            logging.info(f"No schema found for interface {interface_name}, returning all devices with default values")
            devices = self.get_all_devices()
            schema = self.make_default_schema(devices)
            return web.json_response(schema)

        # Build the schema from the database entries
        schema = {}
        for row in schema_devices:
            schema[row["device_name"]] = {
                "group": self.get_group_name(row["device_group"]),
                "starred": bool(row["device_starred"]),
                "priority": row["device_priority"]
            }

        if add_all:
            # Add any devices that are not in the schema with default values
            all_devices = self.get_all_devices()
            for device_name in all_devices:
                if device_name not in schema:
                    schema[device_name] = {
                        "group": None,
                        "starred": False
                    }

        return web.json_response(schema)
