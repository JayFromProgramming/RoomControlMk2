from loguru import logger as logging

from Modules.RoomControl.RoutineControllers.SceneTriggerTypes.SceneTrigger import SceneTrigger


class OccupancyTrigger(SceneTrigger):

    default_trigger_subtype = "on_occupied"
    default_trigger_value = "[any]"

    def __init__(self, scene_controller, scene_id, trigger_id, trigger_subtype, trigger_value, enabled):
        super().__init__(scene_controller, scene_id, trigger_id, trigger_subtype, trigger_value, enabled)
        logging.info(f"Initializing OccupancyTrigger[{self.trigger_id}] for Scene ({scene_id})")

    def exec(self):
        return


