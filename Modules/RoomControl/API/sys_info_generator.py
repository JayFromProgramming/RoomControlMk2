import datetime

from Modules.RoomControl.API.datagrams import APIMessageTX
import logging

logging = logging.getLogger(__name__)

try:
    import psutil
except ImportError:
    psutil = None
    logging.warning("psutil not installed, system info will not be available")


def generate_sys_info() -> APIMessageTX:
    sys_temp = None
    sys_load = None
    sys_mem = None
    sys_uptime = None

    if psutil is not None:
        if hasattr(psutil, "sensors_temperatures"):
            sys_temp = psutil.sensors_temperatures()
            if "cpu_thermal" in sys_temp:
                sys_temp = round(sys_temp["cpu_thermal"][0].current)

        sys_load = round(psutil.cpu_percent())

        sys_mem = f"{psutil.virtual_memory().percent}"

        sys_uptime = round(datetime.datetime.now().timestamp() - psutil.boot_time())

    return APIMessageTX(
        sys_temp=sys_temp,
        sys_load=sys_load,
        sys_mem=sys_mem,
        sys_uptime=sys_uptime,
        prog_uptime=round(datetime.datetime.now().timestamp() - psutil.Process().create_time())
    )
