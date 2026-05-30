import json

from loguru import logger as logging
from aiohttp import web

from Modules.APIModule import APIModule
from Modules.RoomModule import RoomModule


class SchemaHandler(RoomModule, APIModule):

    def __init__(self, room_controller):
        super().__init__(room_controller)
        logging.info("Initializing SchemaHandler module")
        self.room_controller = room_controller
        self.database = room_controller.database
        self.init_database()
        self.import_from_old_schema("testing")

    def get_routes(self):
        return [web.get('/get_schema', self.handle_get_schema),
                web.post('/update_device_schema', self.handle_update_schema),
                web.post('/update_group_schema', self.handle_update_group_schema),
                web.delete('/delete_group_schema', self.handle_delete_group_schema)]

    def init_database(self):
        self.database.run("""
            CREATE TABLE IF NOT EXISTS interface_schema_profiles ( 
            profile_id INTEGER PRIMARY KEY AUTOINCREMENT,
            interface_name TEXT NOT NULL UNIQUE); 
        """)
        self.database.run("""
            CREATE TABLE IF NOT EXISTS interface_schemas_groups(
            profile_id INTEGER REFERENCES interface_schema_profiles(profile_id) ON DELETE CASCADE,
            group_id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_name TEXT NOT NULL,
            group_priority INTEGER,
            UNIQUE(profile_id, group_name));
        """)
        self.database.run("""
            CREATE TABLE IF NOT EXISTS interface_schemas_devices(
            profile_id INTEGER REFERENCES interface_schema_profiles(profile_id) ON DELETE CASCADE,
            device_id TEXT NOT NULL,
            priority INTEGER,
            starred BOOLEAN NOT NULL DEFAULT 0,
            group_id INTEGER REFERENCES interface_schemas_groups(group_id) ON DELETE SET NULL,
            UNIQUE(profile_id, device_id));
        """)

    def get_all_devices(self):
        """
        Gets every device from the room controller which is the default set of devices if an interface has no saved schema"""
        devices = {}
        for obj in self.room_controller.get_all_objects():
            devices[obj.name()] = {
                "group": None,
                "starred": False
            }
        return devices

    @staticmethod
    def make_default_schema(devices):
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
        profile_table = self.database.get_table("interface_schema_profiles")
        existing_profile = profile_table.get_row(interface_name=target_interface)
        if existing_profile:
            logging.info(f"Schema for interface {target_interface} already exists, skipping import")
            return

        logging.info(f"Importing old schema for interface {target_interface}")
        with open("Modules/RoomControl/Configs/new_schema.json", "r") as f:
            old_schema = json.load(f)

        # Create a new profile for the target interface
        profile_entry = profile_table.add(interface_name=target_interface)
        profile_id = profile_entry["profile_id"]

        group_number = 1
        for device_name, device_info in old_schema.items():
            # Check if the group already exists
            group_table = self.database.get_table("interface_schemas_groups")
            if device_info["group"] is not None:
                existing_group = group_table.get_row(group_name=device_info["group"], profile_id=profile_id)
                if existing_group:
                    group_id = existing_group["group_id"]
                else:
                    # Create a new group
                    group_entry = group_table.add(profile_id=profile_id, group_name=device_info["group"], group_priority=group_number)
                    group_id = group_entry["group_id"]
                    group_number += 1
            else:
                group_id = None

            # Insert the device into the devices table
            device_table = self.database.get_table("interface_schemas_devices")
            try:
                device_table.add(profile_id=profile_id,
                                 device_id=device_name,
                                 starred=device_info["starred"],
                                 priority=device_info.get("priority", None),
                                 group_id=group_id)
            except AttributeError:
                pass
        logging.info("Finished importing old schema for testing")

    def get_group_name(self, group_id):
        group_table = self.database.get_table("interface_schemas_groups")
        group_row = group_table.get_row(group_id=group_id)
        if group_row:
            return group_row["group_name"]
        return None

    def get_group_priority(self, group_id):
        group_table = self.database.get_table("interface_schemas_groups")
        group_row = group_table.get_row(group_id=group_id)
        if group_row:
            return group_row["group_priority"]
        return None

    async def handle_update_schema(self, request):
        """
        Device schema update example
        {
            "device_id": {
                "group": "Group Name",
                "starred": true | false,
                "priority": 1 [optional]
            }
        }
        """
        profile_name = request.query.get("interface_name", None)
        if profile_name is None:
            logging.error("interface_name query parameter is required")
            return web.json_response({"error": "interface_name query parameter is required"}, status=400)
        profile_table = self.database.get_table("interface_schema_profiles")
        profile = profile_table.get_row(interface_name=profile_name)
        if not profile:
            logging.error(f"No profile found for interface {profile_name}")
            return web.json_response({"error": f"No profile found for interface {profile_name}"}, status=400)
        profile_id = profile["profile_id"]
        # When updating the schema it happens one device per request, with the json data containing one devices info
        try:
            data = await request.json()
        except Exception as e:
            logging.error(f"Error parsing JSON data: {e}")
            return web.json_response({"error": "Error parsing JSON data"}, status=400)
        if len(data) != 1:
            logging.error("Only one device can be updated at a time")
            return web.json_response({"error": "Only one device can be updated at a time"}, status=400)
        device_id = list(data.keys())[0]
        device_info = data[device_id]
        group_name = device_info.get("group", None)
        starred = device_info.get("starred", False)
        priority = device_info.get("priority", None)
        device_table = self.database.get_table("interface_schemas_devices")
        group_table = self.database.get_table("interface_schemas_groups")
        if group_name is not None:
            group_row = group_table.get_row(group_name=group_name, profile_id=profile_id)
            if not group_row:
                # If the group doesn't exist, create it with the lowest priority
                lowest_priority_group = group_table.get_rows(profile_id=profile_id)
                lowest_priority_group = sorted(lowest_priority_group, key=lambda x: x["group_priority"] if x["group_priority"] is not None else float('inf'))
                if lowest_priority_group and lowest_priority_group[0]["group_priority"] is not None:
                    new_group_priority = lowest_priority_group[0]["group_priority"] + 1
                else:
                    new_group_priority = 1
                group_row = group_table.add(profile_id=profile_id, group_name=group_name, group_priority=new_group_priority)
            group_id = group_row["group_id"]
        else:
            group_id = None
        device_row = device_table.get_row(device_id=device_id, profile_id=profile_id)
        if device_row:
            device_row.set(starred=starred, priority=priority, group_id=group_id)
        else:
            device_table.add(profile_id=profile_id, device_id=device_id, starred=starred, priority=priority, group_id=group_id)
        logging.info(f"Updated schema for device {device_id} in profile {profile_name}")
        return web.json_response({"message": f"Updated schema for device {device_id} in profile {profile_name}"})

    async def handle_update_group_schema(self, request):
        """
        Group schema update example
        {
            "group_name": "Group Name",
            "new_group_name": "New Group Name" [optional],
            "group_priority": 1
        }
        """
        profile_name = request.query.get("interface_name", None)
        if profile_name is None:
            logging.error("interface_name query parameter is required")
            return web.json_response({"error": "interface_name query parameter is required"}, status=400)
        profile_table = self.database.get_table("interface_schema_profiles")
        profile = profile_table.get_row(interface_name=profile_name)
        if not profile:
            logging.error(f"No profile found for interface {profile_name}")
            return web.json_response({"error": f"No profile found for interface {profile_name}"}, status=400)
        profile_id = profile["profile_id"]
        try:
            data = await request.json()
        except Exception as e:
            logging.error(f"Error parsing JSON data: {e}")
            return web.json_response({"error": "Error parsing JSON data"}, status=400)

        group_name = data.get("group_name", None)
        if group_name is None:
            logging.error("group_name is required in the JSON body")
            return web.json_response({"error": "group_name is required in the JSON body"}, status=400)

        new_group_name = data.get("new_group_name", None)
        group_priority = data.get("group_priority", None)

        group_table = self.database.get_table("interface_schemas_groups")
        group_row = group_table.get_row(group_name=group_name, profile_id=profile_id)
        if not group_row:
            logging.error(f"No group found with name {group_name} in profile {profile_name}")
            return web.json_response({"error": f"No group found with name {group_name} in profile {profile_name}"}, status=400)

        # Rename group if requested
        if new_group_name is not None and new_group_name != group_name:
            # Ensure new name doesn't already exist for this profile
            existing = group_table.get_row(group_name=new_group_name, profile_id=profile_id)
            if existing:
                # Check if the existing group actually has any devices in it, if not we can reuse it
                device_table = self.database.get_table("interface_schemas_devices")
                devices_in_existing_group = device_table.get_rows(group_id=existing["group_id"])
                if devices_in_existing_group:
                    logging.error(f"A group with name {new_group_name} already exists in profile {profile_name}")
                    return web.json_response({"error": f"A group with name {new_group_name} already exists in profile {profile_name}"}, status=400)
                # If the existing group has no devices, we can delete it and reuse the name
                group_table.delete(group_id=existing["group_id"])
            try:
                group_row.set(group_name=new_group_name)
                logging.info(f"Renamed group {group_name} -> {new_group_name} in profile {profile_name}")
            except Exception as e:
                logging.error(f"Failed to rename group: {e}")
                return web.json_response({"error": f"Failed to rename group: {e}"}, status=500)

        # Reorder priorities if requested
        if group_priority is not None:
            try:
                desired = int(group_priority)
            except Exception:
                logging.error("group_priority must be an integer")
                return web.json_response({"error": "group_priority must be an integer"}, status=400)
            if desired < 1:
                logging.error("group_priority must be >= 1")
                return web.json_response({"error": "group_priority must be >= 1"}, status=400)

            # Load all groups for this profile except the one being moved
            all_groups = group_table.get_rows(profile_id=profile_id)
            # Convert to list of entries
            other_groups = [g for g in all_groups if g["group_id"] != group_row["group_id"]]
            # Sort by existing priority (None -> inf)
            other_groups = sorted(other_groups, key=lambda x: x["group_priority"] if x["group_priority"] is not None else float('inf'))

            # Clamp desired index
            insert_index = min(desired - 1, len(other_groups))

            # Build new ordered list with the moved group in place
            new_order = other_groups[:insert_index] + [group_row] + other_groups[insert_index:]

            # Reassign sequential priorities starting at 1
            try:
                for idx, grp in enumerate(new_order, start=1):
                    # Only set if different to avoid unnecessary DB writes
                    if grp["group_priority"] != idx:
                        grp.set(group_priority=idx)
                logging.info(f"Reordered groups for profile {profile_name}")
            except Exception as e:
                logging.error(f"Failed to reorder groups: {e}")
                return web.json_response({"error": f"Failed to reorder groups: {e}"}, status=500)

        return web.json_response({"message": f"Updated group {group_name} in profile {profile_name}"})

    async def handle_delete_group_schema(self, request):
        profile_name = request.query.get("interface_name", None)
        if profile_name is None:
            logging.error("interface_name query parameter is required")
            return web.json_response({"error": "interface_name query parameter is required"}, status=400)
        profile_table = self.database.get_table("interface_schema_profiles")
        profile = profile_table.get_row(interface_name=profile_name)
        if not profile:
            logging.error(f"No profile found for interface {profile_name}")
            return web.json_response({"error": f"No profile found for interface {profile_name}"}, status=400)
        profile_id = profile["profile_id"]
        try:
            data = await request.json()
        except Exception as e:
            logging.error(f"Error parsing JSON data: {e}")
            return web.json_response({"error": "Error parsing JSON data"}, status=400)
        group_name = data.get("group_name", None)
        if group_name is None:
            logging.error("group_name is required in the JSON body")
            return web.json_response({"error": "group_name is required in the JSON body"}, status=400)
        group_table = self.database.get_table("interface_schemas_groups")
        group_row = group_table.get_row(group_name=group_name, profile_id=profile_id)
        if not group_row:
            logging.error(f"No group found with name {group_name} in profile {profile_name}")
            return web.json_response({"error": f"No group found with name {group_name} in profile {profile_name}"}, status=400)
        group_table.delete(group_id=group_row["group_id"])
        logging.info(f"Deleted group {group_name} from profile {profile_name}")
        return web.json_response({"message": f"Deleted group {group_name} from profile {profile_name}"})

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

        # Check if a profile exists for the interface_name
        profile_table = self.database.get_table("interface_schema_profiles")
        profile = profile_table.get_row(interface_name=interface_name)
        if not profile:
            # If no profile exists, return all devices with default values
            logging.info(f"No profile found for interface {interface_name}, returning all devices with default values")
            devices = self.get_all_devices()
            schema = self.make_default_schema(devices)
            return web.json_response(schema)

        # Get all devices in the schema for the profile
        profile_id = profile["profile_id"]
        device_table = self.database.get_table("interface_schemas_devices")
        schema_devices = device_table.get_rows(profile_id=profile_id)
        if not schema_devices:
            logging.info(f"No devices found for profile {interface_name}, returning all devices with default values")
            devices = self.get_all_devices()
            schema = self.make_default_schema(devices)
            return web.json_response(schema)

        logging.info(f"Found {len(schema_devices)} devices for profile {interface_name}")


        # Build the schema from the database entries
        schema = {}
        for row in schema_devices:
            schema[row["device_id"]] = {
                "group": self.get_group_name(row["group_id"]),
                "starred": bool(row["starred"]),
                "priority": row["priority"],
                "group_priority": self.get_group_priority(row["group_id"]) # For sorting purposes
            }

        # Sort the schema by group priority, with the lowest priority number first
        schema = dict(sorted(schema.items(), key=lambda item: (item[1]["group_priority"] if item[1]["group_priority"] is not None else float('inf'))))

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
