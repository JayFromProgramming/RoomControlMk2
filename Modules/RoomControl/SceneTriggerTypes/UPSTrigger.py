import datetime
import time

from loguru import logger as logging

from Modules.RoomControl.SceneTriggerTypes.SceneTrigger import SceneTrigger


class UPSTrigger(SceneTrigger):

    default_trigger_subtype = "ups-name"
    default_trigger_value = "condition"

    def __init__(self, scene_controller, scene_id, trigger_id, trigger_subtype, trigger_value, enabled):
        self.room_controller = scene_controller.room_controller
        super().__init__(scene_controller, scene_id, trigger_id, trigger_subtype, trigger_value, enabled)
        logging.info(f"Initializing UPSTrigger[{self.trigger_id}] for Scene ({scene_id})")

    def _prep_UPS_trigger(self, ups_name: str, trigger: str):
        """
        Prepares a timer trigger
        :param interval_type: The type of interval trigger (daily, weekly, hourly)
        :param interval_value: The time of day to trigger the scene either in the format WD*:HH:MM or WD*:HH:MM:SS
        """
        while not self.stopped:
            # Find the UPS device
            ups_device = self.room_controller.get_object(ups_name, create_if_not_found=False)
            if ups_device is None:
                logging.error(f"UPSTrigger[{self.trigger_id}] for Scene ({self.scene_id}) cannot find UPS device ({ups_name})")
                time.sleep(60)
                continue
            if ups_device.get_type() != "UPSDevice":
                logging.error(f"UPSTrigger[{self.trigger_id}] for Scene ({self.scene_id}) found device ({ups_name}) but it is not a UPSDevice")
                time.sleep(60)
                continue
            return ups_device, trigger
        return None

    def exec(self):
        ups_device, trigger = self._prep_UPS_trigger(self.trigger_subtype, self.trigger_value)
        if ups_device is None:
            return
        logging.info(f"UPSTrigger[{self.trigger_id}] for Scene ({self.scene_id}) monitoring UPS device ({ups_device.name()}) for trigger ({trigger})")
        while not self.stopped:
            match trigger:
                case "on_battery":
                    if ups_device.on_battery:
                        logging.info(f"UPSTrigger[{self.trigger_id}] for Scene ({self.scene_id})"
                                     f" triggered by UPS device ({ups_device.name()}) on battery")
                        self.scene_controller.execute_scene(self.scene_id)
                        time.sleep(300)
                case "off_battery":
                    if not ups_device.on_battery:
                        logging.info(f"UPSTrigger[{self.trigger_id}] for Scene ({self.scene_id})"
                                     f" triggered by UPS device ({ups_device.name()}) off battery")
                        self.scene_controller.execute_scene(self.scene_id)
                        time.sleep(300)
            time.sleep(5)