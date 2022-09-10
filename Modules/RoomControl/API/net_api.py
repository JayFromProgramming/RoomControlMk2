import asyncio
import datetime
import logging
import functools

from aiohttp import web
import hashlib

from Modules.RoomControl.API.datagrams import APIMessageTX
from Modules.RoomControl.AbstractSmartDevices import background

logging.getLogger(__name__)


class NetAPI:
    """Used to control VoiceMonkey Devices and set automatic mode for other devices"""

    def __init__(self, database, other_apis):
        self.database = database
        self.other_apis = other_apis
        self.init_database()

        self.app = web.Application()
        self.app.add_routes(
            [web.get('', self.handle_web)]
            + [web.get('/auth/{api_key}', self.handle_auth)]  # When visited it will set a cookie to allow access to the API
            + [web.get('/set/{name}', self.handle_set)]
            + [web.get('/get/{name}', self.handle_get)]
            + [web.get('/get_all', self.handle_get_all)]
        )

        # Set webserver address and port
        self.webserver_address = "localhost"
        self.webserver_port = 47670

        # List of cookies that are authorized to access the API
        cursor = self.database.cursor()
        self.authorized_cookies = [cookie[0] for cookie in cursor.execute("SELECT current_cookie FROM api_authorizations").fetchall()]

        self.runner = web.AppRunner(self.app)
        self.run()

    @background
    def run(self):
        web.run_app(self.app, host=self.webserver_address, port=self.webserver_port)

    def init_database(self):
        cursor = self.database.cursor()
        cursor.execute("CREATE TABLE IF NOT EXISTS "
                       "api_authorizations (device_id TEXT, api_secret TEXT, current_cookie TEXT)")
        cursor.close()
        self.database.commit()

    def get_device(self, device_name):
        for api in self.other_apis:
            if device := api.get_device(device_name):
                return device
        return None

    def get_all_devices(self):
        devices = []
        for api in self.other_apis:
            devices += api.get_all_devices()
        return devices

    def check_auth(self, request):
        """Check if the request has a valid cookie"""
        return request.cookies.get("auth") in self.authorized_cookies

    async def handle_auth(self, request):
        logging.info("Received AUTH request")
        api_key = request.match_info['api_key']
        cursor = self.database.cursor()
        api_secret = cursor.execute("SELECT * FROM api_authorizations WHERE api_secret = ?", (api_key,)).fetchone()
        if api_secret:
            # Make a new cookie based on a hash of the api_secret
            new_cookie = hashlib.sha256(api_secret[0].encode()).hexdigest()
            cursor.execute("UPDATE api_authorizations SET current_cookie = ? WHERE api_secret = ?", (new_cookie, api_key))
            self.database.commit()
            self.authorized_cookies.append(api_secret)
            response = web.Response(text="Authorized")
            response.set_cookie("auth", new_cookie, max_age=60*60*24*365)
            return response
        else:
            raise web.HTTPForbidden(text="Invalid API Key")

    async def handle_get(self, request):
        if not self.check_auth(request):
            raise web.HTTPUnauthorized()

        device_name = request.match_info['name']
        logging.info(f"Received GET request for {device_name}")
        device = self.get_device(device_name)
        msg = APIMessageTX(
            device=device_name,
            status=device.get_status(),
            auto_state=device.auto_state(),
            timestamp=datetime.datetime.now().timestamp()
        )
        if device:
            return web.Response(text=msg.__str__())
        else:
            return web.Response(text="Device not found")

    async def handle_set(self, request):
        if not self.check_auth(request):
            raise web.HTTPUnauthorized()
        device_name = request.match_info['name']
        logging.info(f"Received SET request for {device_name}")
        return web.Response(text="Hello, " + device_name)

    async def handle_get_all(self, request):
        if not self.check_auth(request):
            raise web.HTTPUnauthorized()

        logging.info("Received GET_ALL request")
        msg = APIMessageTX(
            devices=[{device.name(): {
                "status": device.get_status(),
                "type": device.get_type(),
                "auto_state": device.auto_state()}}
                for device in self.get_all_devices()
            ]
        )
        return web.Response(text=msg.__str__())

    async def handle_web(self, request):
        logging.info("Received WEB request")
        return web.Response(text="Hello, World")
