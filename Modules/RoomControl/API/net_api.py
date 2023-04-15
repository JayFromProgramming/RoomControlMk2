import asyncio
import datetime
import json
import functools
import os
import random
import sys
import time

from aiohttp import web
import hashlib

from Modules.RoomControl.API import page_builder
from Modules.RoomControl.API.action_handler import process_device_command
from Modules.RoomControl.API.datagrams import APIMessageTX, APIMessageRX
from Modules.RoomControl.API.sys_info_generator import generate_sys_info
from Modules.RoomControl.AbstractSmartDevices import background

from loguru import logger as logging


def login_redirect():
    return web.HTTPFound("/login")


class NetAPI:
    """Used to control VoiceMonkey Devices and set automatic mode for other devices"""

    def __init__(self, database, device_controllers=None, occupancy_detector=None,
                 scene_controller=None, command_controller=None, webserver_address="localhost",
                 datalogger=None):
        self.database = database  # type: ConcurrentDatabase
        self.other_apis = device_controllers
        self.occupancy_detector = occupancy_detector  # type: BluetoothDetector

        self.scene_controller = scene_controller  # type: SceneController
        self.command_controller = command_controller  # type: CommandController
        self.data_logger = datalogger  # type: DataLoggerHost

        self.init_database()

        self.app = web.Application()
        self.app.add_routes(
            [web.get('', self.handle_web)]
            + [web.get("/page/{page}", self.handle_page)]
            + [web.get('/login', self.handle_login)]
            + [web.post('/login_auth', self.handle_login_auth)]
            + [web.get('/auth/{api_key}', self.handle_auth)]  # When visited it will set a cookie to allow access to the API
            + [web.get('/set/{name}', self.handle_set)]
            + [web.get('/get/{name}', self.handle_get)]
            + [web.post('/set/device_ping_update/{name}', self.handle_device_ping_update)]
            + [web.get('/web_control/{name}', self.handle_web_control)]
            + [web.post('/web_control/{name}', self.handle_web_control)]
            + [web.get('/get_all', self.handle_get_all)]
            + [web.get('/occupancy', self.handle_occupancy)]
            + [web.get('/set_auto/{mode}', self.handle_auto)]
            + [web.get('/get_schema', self.handle_schema)]
            + [web.get('/vm_add/{dev_name}/{on_monkey}/{off_monkey}', self.monkey_adder)]
            + [web.get('/get_scenes', self.handle_get_scenes)]
            + [web.get('/set_scene/{name}', self.handle_set_scene)]
            + [web.get('/get_commands', self.handle_get_commands)]
            + [web.get('/run_command/{name}', self.handle_run_command)]
            + [web.get('/sys_info', self.handle_sys_info)]
            + [web.get('/db_write', self.db_writer)]  # Allows you to write to the database
            + [web.post('/set/{name}', self.handle_set_post)]
            + [web.get('/page/css/{file}', self.handle_css)]
            + [web.get('/page/js/{file}', self.handle_js)]
            + [web.get('/page/img/{file}', self.handle_img)]
            + [web.get('/name/{device_id}', self.handle_name)]
            + [web.get('/get_status_string/{device_id}', self.handle_status_string)]
            + [web.get('/get_health_string/{device_id}', self.handle_health_string)]
            + [web.get('/get_action_string/{device_id}', self.handle_action_string)]
            + [web.get('/get_data_log_sources', self.handle_data_log_sources)]
            + [web.get('/get_data_log/{log_name}/{start}/{end}', self.handle_data_log_get)]
        )

        # Set webserver address and port
        self.webserver_address = webserver_address
        self.webserver_port = 47670

        # List of cookies that are authorized to access the API
        results = self.database.get("SELECT current_cookie FROM login_auth_relations WHERE expires > ?", (time.time(),))
        self.authorized_cookies = [cookie[0] for cookie in results]
        results = self.database.get("SELECT current_cookie FROM api_authorizations")
        self.authorized_cookies += [cookie[0] for cookie in results]
        results = self.database.get("SELECT * FROM login_lockouts")
        self.login_lockouts = {row[0]: {"last_attempt": row[1], "attempts": row[2], "locked_out": row[3]} for row in
                                 results}   # type: dict

        # Load the schema
        with open("Modules/RoomControl/Configs/schema.json") as f:
            self.schema = json.load(f)
        logging.info("Loaded schema")
        self.runner = web.AppRunner(self.app)
        logging.info("Created runner")

    def run(self):
        logging.info("Starting webserver")
        web.run_app(self.app, host=self.webserver_address, port=self.webserver_port,
                    access_log=None)
        logging.error("Webserver stopped")

    def init_database(self):
        self.database.run("CREATE TABLE IF NOT EXISTS "
                          "api_authorizations (device_id TEXT, api_secret TEXT, current_cookie TEXT)")
        self.database.run("""
        CREATE TABLE IF NOT EXISTS login_auth_relations (user_id TEXT UNIQUE REFERENCES api_authorizations(device_id),
        device_name TEXT, current_cookie TEXT, expires INTEGER)""")
        self.database.run("""
        CREATE TABLE IF NOT EXISTS login_lockouts (endpoint TEXT, last_attempt INTEGER, attempts INTEGER, locked_out BOOLEAN)""")

    def get_device(self, device_name):
        for api in self.other_apis:
            if api.get_device(device_name):
                return api.get_device(device_name)
        return None

    def get_all_devices(self):
        devices = []
        for api in self.other_apis:
            devices += api.get_all_devices()
        return devices

    def get_device_display_name(self, device_name):
        """Get the display name for a device from the schema"""
        if self.schema is None:
            return device_name
        for device in self.schema['schema']:
            num = 0
            for d in device["device"] if isinstance(device["device"], list) else [device["device"]]:
                if d == device_name:
                    return device["device_names"][num] if "device_names" in device else device["name"]
                num += 1
        return device_name

    def check_auth(self, request):
        """Check if the request has a valid cookie"""
        logging.debug("NetAPI: Checking auth, cookies: %s", request.cookies)
        if "auth" in request.cookies and request.cookies["auth"] in self.authorized_cookies:
            logging.debug("NetAPI: Auth passed")
            return True
        else:
            logging.debug("NetAPI: Auth failed")
            return False

    async def handle_login(self, request):
        logging.info("Received LOGIN request")

        # Check if the user is already logged in
        if self.check_auth(request):
            return web.HTTPFound("/")

        # Load the login page from "{root}\pages\login_page.html"
        # {root} is the directory that the python script is running from
        with open(f"{sys.path[0]}/Modules/RoomControl/API/pages/login_page.html", "r") as file:
            return web.Response(text=file.read(), content_type="text/html")

    async def handle_login_auth(self, request):
        logging.info("Received LOGIN AUTH request")
        data = await request.post()
        username = data['username']
        password = data['password']
        browser = request.headers.get("User-Agent")
        endpoint = request.remote

        if endpoint in self.login_lockouts and self.login_lockouts[endpoint]["locked_out"]:
            logging.info(f"User {username} attempted to login from {browser} but is locked out")
            return web.Response(text="Locked out", status=403)

        logging.info(f"User: {username}, Password: {password}, Browser: {browser}, Endpoint: {endpoint}")
        cursor = self.database.cursor()
        user = cursor.execute("SELECT * FROM api_authorizations WHERE device_id=?", (username,)).fetchone()
        if user is None:
            logging.info(f"User {username} does not exist")
            return web.Response(text="User does not exist", status=401)
        else:
            logging.info(f"User: {user[0]}, Password: {user[1]}")
        if user and user[1] == password:
            new_cookie = hashlib.sha256(f"{password}: {random.random()}".encode()).hexdigest()

            cursor.execute("""INSERT OR REPLACE INTO login_auth_relations (user_id, device_name, current_cookie, expires) 
                           VALUES (?, ?, ?, ?)""", (username, browser, new_cookie, int(time.time()) + 60 * 60 * 24 * 7))
            logging.info(f"User {username} logged in from {browser}")
            response = web.Response(text="Authorized", status=302)
            response.set_cookie("auth", new_cookie, max_age=60 * 60 * 24 * 365)

            self.authorized_cookies.append(new_cookie)

            cursor.close()
            self.database.commit()
            # Redirect to the main page
            response.headers["Location"] = "/"
            return response
        else:
            logging.info(f"Host: {endpoint} failed to login")
            if endpoint not in self.login_lockouts:
                self.login_lockouts[endpoint] = {"last_attempt": time.time(), "attempts": 1, "locked_out": False}
            else:
                self.login_lockouts[endpoint]["attempts"] += 1
                if self.login_lockouts[endpoint]["attempts"] > 5:
                    self.login_lockouts[endpoint]["locked_out"] = True
                    self.login_lockouts[endpoint]["last_attempt"] = time.time()
                    logging.info(f"Host: {endpoint} has been locked out")
                else:
                    self.login_lockouts[endpoint]["last_attempt"] = time.time()
            cursor.close()
            raise web.HTTPUnauthorized()

    async def handle_auth(self, request):
        logging.info("Received AUTH request")
        api_key = request.match_info['api_key']
        cursor = self.database.cursor()
        api_secret = cursor.execute("SELECT * FROM api_authorizations WHERE api_secret = ?", (api_key,)).fetchone()
        if api_secret:
            logging.info("API key is valid")
            # Make a new cookie based on a hash of the api_secret
            new_cookie = hashlib.sha256(api_secret[0].encode()).hexdigest()
            cursor.execute("UPDATE api_authorizations SET current_cookie = ? WHERE api_secret = ?", (new_cookie, api_key))
            self.database.commit()
            self.authorized_cookies.append(api_secret)
            response = web.Response(text="Authorized")
            response.set_cookie("auth", new_cookie, max_age=60 * 60 * 24 * 365)
            return response
        else:
            logging.info("API key is invalid")
            raise web.HTTPForbidden(text="Invalid API Key")

    async def handle_get(self, request):
        if not self.check_auth(request):
            return login_redirect()

        device_name = request.match_info['name']
        logging.debug(f"Received GET request for {device_name}")
        device = self.get_device(device_name)
        msg = APIMessageTX(
            state=device.get_state(),
            info=device.get_info(),
            health=device.get_health(),
            type=device.get_type(),
            auto_state=device.auto_state()
        )
        if device:
            return web.Response(text=msg.__str__(), headers={"Refresh": "5"})
        else:
            return web.Response(text="Device not found")

    async def handle_set(self, request):
        if not self.check_auth(request):
            raise web.HTTPUnauthorized()
        device_name = request.match_info['name']
        logging.info(f"Received SET request for {device_name}")
        data = request.query

        # if "redirect" in data:
        #     redirect = data["redirect"]

        msg = APIMessageRX(data)
        device = self.get_device(device_name)
        result, success = process_device_command(device, msg)
        # Add a redirect to the response to the main page
        if not success:
            return web.Response(text=result, status=503)
        response = web.Response(text=result.__str__(), status=302)
        response.headers['Location'] = "/"
        return response

    async def handle_set_post(self, request):
        if not self.check_auth(request):
            raise web.HTTPUnauthorized()
        device_name = request.match_info['name']
        logging.info(f"Received POST SET request for {device_name}")
        data = await request.json()
        logging.info(f"Received data: {data}")
        msg = APIMessageRX(data)
        device = self.get_device(device_name)
        result, success = process_device_command(device, msg)
        if not success:
            return web.Response(text=result, status=503)
        return web.Response(text=result.__str__())

    async def handle_get_all(self, request):
        if not self.check_auth(request):
            raise web.HTTPUnauthorized()

        logging.debug("Received GET_ALL request")
        devices_raw = self.get_all_devices()
        devices = {}
        for device in devices_raw:
            if isinstance(device, str):
                devices[device] = device
            else:
                devices[device.name()] = {
                    "state": device.get_state(),
                    "info": device.get_info(),
                    "health": device.get_health(),
                    "type": device.get_type(),
                    "auto_state": device.auto_state()}
        msg = APIMessageTX(
            devices=devices
        )
        return web.Response(text=msg.__str__(), headers={"Refresh": "5"})

    async def handle_web(self, request):
        if not self.check_auth(request):
            return login_redirect()

        # Redirect to the main page /page/main
        response = web.Response(text="Authorized", status=302)

        response.headers["Location"] = "/page/main"
        return response

    async def handle_page(self, request):
        if not self.check_auth(request):
            return login_redirect()

        page = request.match_info['page']

        # Make sure the page is valid and not a path traversal attack
        if not page or page.startswith(".") or "/" in page:
            return web.Response(text="Invalid page", status=404)

        if os.path.isfile(f"{sys.path[0]}/Modules/RoomControl/API/pages/{page}.html"):
            with open(f"{sys.path[0]}/Modules/RoomControl/API/pages/{page}.html", "r") as file:
                return web.Response(text=file.read(), content_type="text/html")
        else:
            logging.warning(f"Page {sys.path[0]}/Modules/RoomControl/API/pages/{page}.html not found")
            return web.Response(text="Page not found", status=404)

    async def handle_web_control(self, request):
        if not self.check_auth(request):
            raise web.HTTPUnauthorized()

        logging.debug("Received WEB CONTROL request")

        # Load the main page from "{root}\pages\main_view_page.html"
        device = request.match_info['name']
        hw_device = self.get_device(device)

        return page_builder.generate_control_page(self, hw_device)

    async def handle_web_control_post(self, request):
        if not self.check_auth(request):
            raise web.HTTPUnauthorized()

        logging.debug("Received WEB CONTROL POST request")

        data = await request.post()
        device_name = data['name']
        logging.info(f"Received POST SET request for {device_name}")
        msg = APIMessageRX(data)
        device = self.get_device(device_name)
        result = process_device_command(device, msg)
        return web.Response(text=result.__str__())

    async def handle_occupancy(self, request):
        if not self.check_auth(request):
            raise web.HTTPUnauthorized()
        logging.debug("Received OCCUPANCY request")
        return web.Response(text=str(self.occupancy_detector.get_occupancy()), headers={"Refresh": "5"})

    async def handle_auto(self, request):
        if not self.check_auth(request):
            raise web.HTTPUnauthorized()
        mode = request.match_info['mode']
        logging.debug(f"Received AUTO request for {mode}")
        for api in self.other_apis:
            api.set_auto_mode(mode)
        return web.Response(text="OK")

    async def handle_schema(self, request):
        if not self.check_auth(request):
            raise web.HTTPUnauthorized()
        logging.debug("Received SCHEMA request")

        return web.Response(text=json.dumps(self.schema))

    async def monkey_adder(self, request):
        logging.debug("Received MONKEY_ADDER request")
        if not self.check_auth(request):
            raise web.HTTPUnauthorized()
        device_name = request.match_info['dev_name']
        on_monkey = request.match_info['on_monkey']
        off_monkey = request.match_info['off_monkey']
        self.database.execute(
            "INSERT INTO voicemonkey_devices (device_name, on_monkey, off_monkey) VALUES (?, ?, ?)",
            (device_name, on_monkey, off_monkey))
        self.database.commit()

        return web.Response(text="Device added")

    async def db_writer(self, request):
        logging.info("Received DB_WRITER request")
        if not self.check_auth(request):
            raise web.HTTPUnauthorized()

        data = await request.content.readexactly(request.content_length)
        logging.info(f"Received data: {data}")

        cursor = self.database.cursor()
        data = str(data, 'utf-8')
        result = cursor.execute(data)
        self.database.commit()

        return web.Response(text=str(result))

    async def handle_css(self, request):
        if not self.check_auth(request):
            raise web.HTTPUnauthorized()
        logging.info("Received CSS request")

        file = request.match_info['file']
        logging.info(f"Received CSS request for {file}")
        # Check if the file exists
        file_path = rf"{sys.path[0]}/Modules/RoomControl/API/pages/css/{file}"
        if not os.path.isfile(file_path) or True:
            return web.FileResponse(file_path)
        else:
            logging.error(f"CSS file {file_path} not found")
            return web.HTTPNotFound()

    async def handle_js(self, request):
        if not self.check_auth(request):
            raise web.HTTPUnauthorized()
        logging.info("Received JS request")

        file = request.match_info['file']
        logging.info(f"Received JS request for {file}")
        # Check if the file exists
        if os.path.isfile(rf"{sys.path[0]}/Modules/RoomControl/API/pages/js/{file}"):
            return web.FileResponse(rf"{sys.path[0]}/Modules/RoomControl/API/pages/js/{file}")
        else:
            return web.HTTPNotFound()

    async def handle_img(self, request):
        if not self.check_auth(request):
            raise web.HTTPUnauthorized()
        logging.info("Received IMG request")

        file = request.match_info['file']
        logging.info(f"Received IMG request for {file}")
        # Check if the file exists
        if os.path.isfile(rf"{sys.path[0]}/Modules/RoomControl/API/pages/img/{file}"):
            return web.FileResponse(rf"{sys.path[0]}/Modules/RoomControl/API/pages/img/{file}")
        else:
            return web.HTTPNotFound()

    async def handle_get_scenes(self, request):
        if not self.check_auth(request):
            raise web.HTTPUnauthorized()
        logging.debug("Received GET_SCENES request")

        if self.scene_controller is None:
            msg = APIMessageTX(error="Scene controller not found")
        else:
            msg = APIMessageTX(scenes=self.scene_controller.get_scenes())

        return web.Response(text=msg.__str__())

    async def handle_set_scene(self, request):
        if not self.check_auth(request):
            raise web.HTTPUnauthorized()
        logging.info("Received SET_SCENE request")

        if self.scene_controller is None:
            msg = APIMessageTX(error="Scene controller not found")
        else:
            scene_name = request.match_info['name']
            result = self.scene_controller.execute_trigger(scene_name)
            msg = APIMessageTX(result=result)

        return web.Response(text=msg.__str__())

    async def handle_get_commands(self, request):
        if not self.check_auth(request):
            raise web.HTTPUnauthorized()
        logging.debug("Received GET_COMMANDS request")

        if self.command_controller is None:
            msg = APIMessageTX(error="Scene controller not found")
        else:
            msg = APIMessageTX(commands=self.command_controller.get_commands())

        return web.Response(text=msg.__str__())

    async def handle_run_command(self, request):
        if not self.check_auth(request):
            raise web.HTTPUnauthorized()
        logging.info("Received RUN_COMMAND request")

        if self.command_controller is None:
            msg = APIMessageTX(error="Scene controller not found")
        else:
            command_name = request.match_info['name']
            self.command_controller.run_command(command_name)
            msg = APIMessageTX()

        return web.Response(text=msg.__str__())

    async def handle_sys_info(self, request):
        if not self.check_auth(request):
            raise web.HTTPUnauthorized()
        logging.debug("Received SYS_INFO request")

        return web.Response(text=generate_sys_info().__str__())

    async def handle_name(self, request):
        if not self.check_auth(request):
            raise web.HTTPUnauthorized()
        # logging.info("Received NAME request")
        device_id = request.match_info['device_id']
        device_name = self.get_device_display_name(device_id)
        return web.Response(text=device_name)

    async def handle_status_string(self, request):
        if not self.check_auth(request):
            raise web.HTTPUnauthorized()
        # logging.info("Received STATUS_STRING request")
        device_id = request.match_info['device_id']
        device = self.get_device(device_id)
        device_status = page_builder.state_to_string(device)
        return web.Response(text=device_status)

    async def handle_health_string(self, request):
        if not self.check_auth(request):
            raise web.HTTPUnauthorized()
        # logging.info("Received HEALTH_STRING request")
        device_id = request.match_info['device_id']
        device = self.get_device(device_id)
        device_health = page_builder.health_message(device)
        return web.Response(text=device_health)

    async def handle_action_string(self, request):
        if not self.check_auth(request):
            raise web.HTTPUnauthorized()
        # logging.info("Received ACTION_STRING request")
        device_id = request.match_info['device_id']
        device = self.get_device(device_id)
        device_action = page_builder.generate_actions(device)
        return web.Response(text=device_action)

    async def handle_data_log_sources(self, request):
        if not self.check_auth(request):
            raise web.HTTPUnauthorized()
        # logging.info("Received DATA_LOG_SOURCES request")
        presets = self.data_logger.get_presets()
        msg = APIMessageTX(presets=presets)
        return web.Response(text=msg.__str__())

    async def handle_data_log_get(self, request):
        if not self.check_auth(request):
            raise web.HTTPUnauthorized()
        # logging.info("Received DATA_LOG request")
        source = request.match_info['log_name']
        start = request.match_info['start']
        end = request.match_info['end']
        data = self.data_logger.get_data(source, start, end)
        msg = APIMessageTX(data_log=data, source=source)
        return web.Response(text=msg.__str__())

    async def handle_device_ping_update(self, request):
        if not self.check_auth(request):
            raise web.HTTPUnauthorized()
        # logging.info("Received DEVICE_PING_UPDATE request")
        device_id = request.match_info['device_id']
        device = self.get_device(device_id)
        device.ping()
        return web.Response(text="OK")
