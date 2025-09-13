from aiohttp.web_routedef import RouteDef
from loguru import logger as logging

class APIModule:

    def __init__(self):
        self.net_api = None

    def pass_network_api(self, net_api):
        self.net_api = net_api

    def check_auth(self, request) -> bool:
        if self.net_api is None:
            logging.error("Network API not set in an instance of an APIModule")
            return False
        return self.net_api.check_auth(request)

    def get_routes(self) -> list[RouteDef]:
        return []






