import asyncio
import datetime
import json
import functools
import os
import random
import sys
import threading
import time

import netifaces
from aiohttp import web
import hashlib

# from Modules.RoomControl.API import page_builder
from Modules.RoomControl.API.action_handler import process_device_command
from Modules.RoomControl.API.datagrams import APIMessageTX, APIMessageRX
from Modules.RoomControl.API.name_handler import NameHandler
from Modules.RoomControl.API.sys_info_generator import generate_sys_info
from Modules.RoomControl.Decorators import background

from loguru import logger as logging

from Modules.RoomModule import RoomModule


def login_redirect():
    return web.HTTPFound("/login")


def get_host_names():
    """
    Gets all the ip addresses that can be bound to
    """
    interfaces = []
    for interface in netifaces.interfaces():
        try:
            if netifaces.AF_INET in netifaces.ifaddresses(interface):
                for link in netifaces.ifaddresses(interface)[netifaces.AF_INET]:
                    if link["addr"] != "":
                        interfaces.append(link["addr"])
        except Exception as e:
            logging.debug(f"Error getting interface {interface}: {e}")
            pass
    return interfaces


IP_BLACKLIST = ["83.97"]

lock = asyncio.Lock()


async def blacklist_middleware(app, handler):
    async def middleware_handler(request):
        # await lock.acquire()
        await asyncio.sleep(random.random() * 0.5)  # Add variable delay to response to show off lazy loading
        for ip in IP_BLACKLIST:
            if request.remote.startswith(ip):
                logging.debug(f"Blacklisted IP {request.remote} attempted to access the API")
                # lock.release()
                return web.Response(status=403)  # Forbidden
        # lock.release()
        return await handler(request)

    return middleware_handler


async def on_prepare(request, response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    response.headers["Access-Control-Max-Age"] = "3600"

    if request.method == "OPTIONS":
        return web.Response(status=200)


class NetAPI(RoomModule):
    """Used to control VoiceMonkey Devices and set automatic mode for other devices"""

    is_webserver = True

    def __init__(self, room_controller):
        super().__init__(room_controller)
        self.room_controller = room_controller
        self.database = room_controller.database
        self.occupancy_detector = room_controller.get_module("OccupancyDetector")

        self.scene_controller = room_controller.get_module("SceneController")
        self.command_controller = room_controller.get_module("CommandController")
        # self.data_logger = datalogger  # type: # DataLoggerHost
        self.name_handler = NameHandler(room_controller)

        self.init_database()

        self.app = web.Application(middlewares=[blacklist_middleware])
        self.app.on_response_prepare.append(on_prepare)
        self.app.add_routes(  # Yes this could be done with a loop, but this is easier for me to keep track of
            [web.get('', self.handle_web)]
            + [web.get("/page/{page}", self.handle_page)]
            + [web.get('/login', self.handle_login)]
            + [web.post('/login_auth', self.handle_login_auth)]
            + [web.get('/auth/{api_key}', self.handle_auth)]
            + [web.get('/set/{name}', self.handle_set)]
            + [web.get('/get/{name}', self.handle_get)]
            + [web.get('/get_type/{name}', self.handle_get_type)]
            + [web.post('/set/device_ping_update/{name}', self.handle_device_ping_update)]
            + [web.get('/get_all', self.handle_get_all)]
            # + [web.get('/occupancy', self.handle_occupancy)]
            # + [web.get('/set_auto/{mode}', self.handle_auto)]
            + [web.get('/get_schema', self.handle_schema)]
            # + [web.get('/vm_add/{dev_name}/{on_monkey}/{off_monkey}', self.monkey_adder)]
            + [web.get('/scene_get/{value}/{target}', self.handle_get_scenes)]
            + [web.post('/scene_action/{action}/{scene_id}', self.handle_scene_command)]
            + [web.get('/run_command/{name}', self.handle_run_command)]
            + [web.get('/sys_info', self.handle_sys_info)]
            + [web.get('/get_system_monitors', self.handle_system_monitors)]
            + [web.get('/db_write', self.db_writer)]  # Allows you to write to the database
            + [web.post('/set/{name}', self.handle_set_post)]
            + [web.get('/page/css/{file}', self.handle_css)]
            + [web.get('/page/js/{file}', self.handle_js)]
            + [web.get('/page/img/{file}', self.handle_img)]
            + [web.get('/name/{device_id}', self.handle_name)]
            + [web.get('/set_name/{device_id}/{new_name}', self.set_name)]
            + [web.get('/get_data_log_sources', self.handle_data_log_sources)]
            + [web.get('/get_data_log/{log_name}/{start}/{end}', self.handle_data_log_get)]
            + [web.get('/weather/now', self.handle_weather_now)]
            + [web.get('/weather/available_forecast', self.handle_weather_forecast_list)]
            + [web.get('/weather/forecast/{time}', self.handle_weather_forecast)]
            + [web.get('/weather/past/{from_time}/{to_time}', self.handle_weather_past)]
            + [web.get('/weather/available_radars', self.handle_radar_list)]
            + [web.get('/weather/radar/{timestamp}/{x}/{y}/{color}', self.handle_radar)]
        )

        # Set webserver address and port
        self.webserver_address = get_host_names()
        self.webserver_port = 80

        # List of cookies that are authorized to access the API
        results = self.database.get("SELECT current_cookie FROM login_auth_relations WHERE expires > ?", (time.time(),))
        self.authorized_cookies = [cookie[0] for cookie in results]
        results = self.database.get("SELECT current_cookie FROM api_authorizations")
        self.authorized_cookies += [cookie[0] for cookie in results]
        results = self.database.get("SELECT * FROM login_lockouts")
        self.login_lockouts = {row[0]: {"last_attempt": row[1], "attempts": row[2], "locked_out": row[3]} for row in
                               results}  # type: dict
        logging.info(f"Loaded {len(self.authorized_cookies)} authorized cookies")
        logging.info(f"Loaded {len(self.login_lockouts)} login lockouts")

        # Load the schema
        # with open("Modules/RoomControl/Configs/schema.json") as f:
        #     self.schema = json.load(f)
        logging.info("Loaded schema")
        # self.app.logger = None
        self.runner = web.AppRunner(self.app, access_log=None)
        logging.info("Created runner")

    async def get_site(self):
        await self.runner.setup()
        site = web.TCPSite(self.runner, self.webserver_address, self.webserver_port)
        return site

    def init_database(self):
        self.database.run("CREATE TABLE IF NOT EXISTS "
                          "api_authorizations (device_id TEXT, api_secret TEXT, current_cookie TEXT)")

        self.database.run("""
        CREATE TABLE IF NOT EXISTS login_auth_relations 
        (user_id TEXT REFERENCES api_authorizations(device_id),
        device_name TEXT, current_cookie TEXT, expires INTEGER,
        PRIMARY KEY (user_id, device_name))""")

        self.database.run("""
        CREATE TABLE IF NOT EXISTS login_lockouts 
        (endpoint TEXT, last_attempt INTEGER, attempts INTEGER, locked_out BOOLEAN)""")

    def get_device(self, device_name):
        return self.room_controller.get_object(device_name, create_if_not_found=False)

    def get_all_devices(self):
        return self.room_controller.get_all_objects()

    def get_device_display_name(self, device_name):
        """Get the display name for a device from the schema"""
        # Get the device object from room controller
        device = self.get_device(device_name)
        if not device:
            response = web.Response(text="Device not found", status=404)
            return False
        if name := device.get_display_name():
            return name
        return self.name_handler.get_name(device_name)

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
        logging.info(f"Received LOGIN request from {request.remote}")

        # Check if the user is already logged in
        if self.check_auth(request):
            return web.HTTPFound("/")

        # Load the login page from "{root}\pages\login_page.html"
        # {root} is the directory that the python script is running from
        with open(f"{sys.path[0]}/Modules/RoomControl/API/pages/login_page.html", "r") as file:
            return web.Response(text=file.read(), content_type="text/html")

    async def handle_login_auth(self, request):
        logging.info("Received LOGIN AUTH request")
        data = await request.post()  # type: dict
        username = data['username']
        password = data['password']
        # Get unique device id from the client (user-agent is insufficient)
        # The device id is stored in the cookies
        device_id = request.cookies.get("uniqueID", None)
        if device_id is None:
            logging.warning("Received LOGIN AUTH request without uniqueID cookie")
            raise web.HTTPBadRequest()
        endpoint = request.remote

        if endpoint in self.login_lockouts and self.login_lockouts[endpoint]["locked_out"]:
            logging.info(f"User {username} attempted to login from {device_id} but is locked out")
            return web.Response(text="Locked out", status=403)

        logging.info(f"User: {username}, Password: {password}, Browser: {device_id}, Endpoint: {endpoint}")
        cursor = self.database.cursor()
        user = cursor.execute("SELECT * FROM api_authorizations WHERE device_id=?", (username,)).fetchone()
        if user is None:
            logging.info(f"User {username} does not exist")
            return web.Response(text="User does not exist", status=401)
        if user and user[1] == password:
            expiry_time = int(time.time()) + 60 * 60 * 24 * 30  # 7 days
            new_cookie = hashlib.sha256(f"{password}: {random.random()}".encode()).hexdigest()
            # Check if the device already exists in the database, if so, update the cookie
            existing_device = cursor.execute("SELECT * FROM login_auth_relations WHERE user_id=? AND device_name=?",
                                             (username, device_id)).fetchone()
            if existing_device:
                cursor.execute(
                    "UPDATE login_auth_relations SET current_cookie=?, expires=? WHERE user_id=? AND device_name=?",
                    (new_cookie, expiry_time, username, device_id))
            else:
                cursor.execute("""INSERT INTO login_auth_relations 
                    (user_id, device_name, current_cookie, expires) VALUES (?, ?, ?, ?)""",
                               (username, device_id, new_cookie, expiry_time))
            logging.info(f"User {username} logged in from {device_id}")
            response = web.Response(text="Authorized", status=302)
            response.set_cookie("auth", new_cookie, max_age=expiry_time)

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
            cursor.execute("UPDATE api_authorizations SET current_cookie = ? WHERE api_secret = ?",
                           (new_cookie, api_key))
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
        if device:
            msg = APIMessageTX(
                state=device.get_state(),
                info=device.get_info(),
                health=device.get_health(),
                type=device.get_type(),
                auto_state=device.auto_state()
            )
            return web.Response(text=msg.__str__(), headers={"Refresh": "5"})
        else:
            return web.Response(text="Device not found")

    async def handle_get_type(self, request):
        if not self.check_auth(request):
            return login_redirect()

        device_name = request.match_info['name']
        logging.debug(f"Received GET_TYPE request for {device_name}")
        device = self.get_device(device_name)
        if device:
            return web.Response(text=device.get_type())
        else:
            return web.Response(text="Device not found")

    async def handle_set(self, request):
        if not self.check_auth(request):
            raise web.HTTPUnauthorized()
        device_name = request.match_info['name']
        logging.info(f"Received SET request for {device_name} from {request.remote}")
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
        logging.info(f"Received POST SET request for {device_name} from {request.remote}")
        data = await request.json()
        logging.info(f"Received data: {data}")
        msg = APIMessageRX(data)
        device = self.get_device(device_name)
        result, success = process_device_command(device, msg)
        if not success:
            return web.Response(text=result.__str__(), status=503)
        return web.Response(text=result.__str__())

    async def handle_get_all(self, request):
        if not self.check_auth(request):
            raise web.HTTPUnauthorized()

        logging.debug("Received GET_ALL request")
        devices_raw = self.get_all_devices()
        # Sort the devices by type
        devices_raw.sort(key=lambda x: x.object_type, reverse=True)
        devices = {}

        for device in devices_raw:
            try:
                if isinstance(device, str):
                    devices[device] = device
                else:
                    name = device.object_name
                    devices[name] = {
                        "state": device.get_state(),
                        "info": device.get_info(),
                        "actions": device.supported_actions,
                        "health": device.get_health(),
                        "type": "Promise" if device.object_type == "RoomObject" else device.get_type(),
                        "auto_state": device.auto_state()
                    }
            except Exception as e:
                logging.error(f"Error getting data for {device}: {e}")
                logging.exception(e)

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

    # async def handle_web_control(self, request):
    #     if not self.check_auth(request):
    #         raise web.HTTPUnauthorized()
    #
    #     logging.debug("Received WEB CONTROL request")
    #
    #     # Load the main page from "{root}\pages\main_view_page.html"
    #     device = request.match_info['name']
    #     hw_device = self.get_device(device)
    #
    #     return page_builder.generate_control_page(self, hw_device)

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
        with open("Modules/RoomControl/Configs/new_schema.json") as f:
            return web.Response(text=f.read(), content_type="application/json")

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
            # logging.error(f"CSS file {file_path} not found")
            return web.HTTPNotFound()

    async def handle_js(self, request):
        if not self.check_auth(request):
            raise web.HTTPUnauthorized()
        logging.info("Received JS request")

        file = request.match_info['file']
        # logging.info(f"Received JS request for {file}")
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
        # logging.info(f"Received IMG request for {file}")
        # Check if the file exists
        if os.path.isfile(rf"{sys.path[0]}/Modules/RoomControl/API/pages/img/{file}"):
            return web.FileResponse(rf"{sys.path[0]}/Modules/RoomControl/API/pages/img/{file}")
        else:
            return web.HTTPNotFound()

    async def handle_get_scenes(self, request):
        if not self.check_auth(request):
            raise web.HTTPUnauthorized()
        logging.debug("Received GET_SCENES request")

        if self.room_controller.get_module("SceneController") is None:
            msg = APIMessageTX(error="Scene controller not found")
        else:
            value = request.match_info['value']
            target = request.match_info['target']
            msg = APIMessageTX(result=self.room_controller.get_module("SceneController").execute_get(value, target))

        return web.Response(text=msg.__str__())

    async def handle_scene_command(self, request):
        if not self.check_auth(request):
            raise web.HTTPUnauthorized()
        logging.info("Received SET_SCENE request")

        if self.room_controller.get_module("SceneController") is None:
            msg = APIMessageTX(error="Scene controller not found")
        else:
            command = request.match_info['action']
            scene_id = request.match_info['scene_id']
            payload = await request.json()
            result = self.room_controller.get_module("SceneController"). \
                execute_command(command, scene_id, payload)
            msg = APIMessageTX(result=result)

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
        if device_name is False:
            return web.Response(text="Device not found", status=404)
        return web.Response(text=device_name)

    async def set_name(self, request):
        if not self.check_auth(request):
            raise web.HTTPUnauthorized()
        # logging.info("Received SET_NAME request")
        device_id = request.match_info['device_id']
        new_name = request.match_info['new_name']
        self.name_handler.set_name(device_id, new_name)
        return web.Response(text="OK")

    async def handle_data_log_sources(self, request):
        if not self.check_auth(request):
            raise web.HTTPUnauthorized()
        # logging.info("Received DATA_LOG_SOURCES request")
        presets = self.room_controller.get_module("DataLoggingHost").get_presets()
        msg = APIMessageTX(presets=presets)
        return web.Response(text=msg.__str__())

    async def handle_data_log_get(self, request):
        if not self.check_auth(request):
            raise web.HTTPUnauthorized()
        # logging.info("Received DATA_LOG request")
        source = request.match_info['log_name']
        start = request.match_info['start']
        end = request.match_info['end']
        data = self.room_controller.get_module("DataLoggingHost").get_data(source, start, end)
        msg = APIMessageTX(data_log=data, source=source)
        return web.Response(text=msg.__str__())

    async def handle_weather_now(self, request):
        # if not self.check_auth(request):
        #     raise web.HTTPUnauthorized()
        # logging.info("Received WEATHER_NOW request")
        if self.room_controller.get_module("WeatherRelay") is None:
            return web.Response(text="Weather module not found", status=503)
        if self.room_controller.get_module("WeatherRelay").current_weather is None:
            return web.Response(text="Weather data not found", status=503)
        weather = self.room_controller.get_module("WeatherRelay").current_weather.to_dict()
        weather["wanted_location"] = self.room_controller.get_module("WeatherRelay").location_latlong
        weather["actual_location"] = str(self.room_controller.get_module("WeatherRelay").actual_location)
        return web.json_response(weather)

    async def handle_weather_forecast_list(self, request):
        # if not self.check_auth(request):
        #     raise web.HTTPUnauthorized()
        # logging.info("Received WEATHER_FORECAST_LIST request")
        if self.room_controller.get_module("WeatherRelay") is None:
            return web.Response(text="Weather module not found", status=503)
        data = self.room_controller.get_module("WeatherRelay").get_available_forecast()
        msg = APIMessageTX(weather_forecast_list=data)
        return web.Response(text=msg.__str__())

    async def handle_weather_forecast(self, request):
        # if not self.check_auth(request):
        #     raise web.HTTPUnauthorized()
        # logging.info("Received WEATHER_FORECAST request")
        data = self.room_controller.get_module("WeatherRelay").get_forecast(request.match_info['time'])
        msg = APIMessageTX(weather_forecast=data.to_dict())
        return web.Response(text=msg.__str__())

    async def handle_weather_past(self, request):
        # if not self.check_auth(request):
        #     raise web.HTTPUnauthorized()
        # logging.info("Received WEATHER_PAST request")
        data = self.room_controller.get_module("WeatherRelay").get_past()
        msg = APIMessageTX(weather_past=data)
        return web.Response(text=msg.__str__())

    async def handle_radar_list(self, request):
        data = self.room_controller.get_module("WeatherRelay").get_available_radar()
        msg = APIMessageTX(weather_radar_list=data)
        return web.Response(text=msg.__str__())

    async def handle_radar(self, request):
        timestamp = request.match_info['timestamp']
        x = request.match_info['x']
        y = request.match_info['y']
        color = request.match_info['color']
        data = self.room_controller.get_module("WeatherRelay").get_radar_tile(timestamp, x, y, color)
        if data is None:
            return web.Response(status=404)
        return web.Response(body=data, content_type="image/png")

    async def handle_device_ping_update(self, request):
        if not self.check_auth(request):
            raise web.HTTPUnauthorized()
        # logging.info("Received DEVICE_PING_UPDATE request")
        device_id = request.match_info['device_id']
        device = self.get_device(device_id)
        device.ping()
        return web.Response(text="OK")

    async def handle_system_monitors(self, request):
        if not self.check_auth(request):
            raise web.HTTPUnauthorized()
        # logging.info("Received SYSTEM_MONITORS request")
        # Get all room objects of type "SystemMonitor" or "satellite_SystemMonitor"
        monitors = self.room_controller.get_type("SystemMonitor")
        print(monitors)
        # List all the monitor names and nothing more
        data = [monitor.object_name for monitor in monitors]
        msg = APIMessageTX(system_monitors=data)
        return web.Response(text=msg.__str__())
