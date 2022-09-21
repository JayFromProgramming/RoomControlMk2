import logging
import os

logging = logging.getLogger(__name__)


class CommandController:
    """Executes system commands on the room controller,
     these commands are hardcoded in the room controller and not stored in the database"""

    def __init__(self, room_controllers):
        self.room_controllers = room_controllers
        self.devices = []

        for room_controller in self.room_controllers:
            self.devices.extend(room_controller.get_all_devices())

        self.commands = {
            "reboot": {"name": "Reboot"},
            "shutdown": {"name": "Shutdown"},
            "update": {"name": "Update"},
            "power_off": {"name": "Power Off"},

        }

    def get_commands(self):
        return self.commands

    def run_command(self, command):

        match command:
            case "reboot":
                self._reboot()
            case "shutdown":
                self._shutdown()
            case "update":
                self._update()
            case "power_off":
                self._power_off()
            case _:
                logging.warning(f"CommandController: Command {command} not recognised")

    def _reboot(self):
        logging.info("Rebooting system")
        for device in self.devices:
            if hasattr(device, "on"):
                device.on = False
        # Send reboot command to room controller
        os.system("sudo reboot")

    def _shutdown(self):
        logging.info("Shutting down system")
        # Send shutdown command to room controller
        os.system("sudo shutdown -h now")

    def _update(self):
        logging.info("Updating room controller")

        os.system("git pull")
        os.system("sudo systemctl restart room_controller.service")

    def _power_off(self):
        logging.info("Powering off all devices")
        for device in self.devices:
            if hasattr(device, "on"):
                device.on = False

        os.system("sudo shutdown -h now")