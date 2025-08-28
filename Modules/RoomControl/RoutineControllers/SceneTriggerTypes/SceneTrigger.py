from Modules.RoomControl import background


class SceneTrigger:
    """
    This is a derived class that represents a trigger for a scene.
    """

    default_trigger_subtype = None
    default_trigger_value = None

    def __init__(self, scene_controller, scene_id, trigger_id, trigger_subtype, trigger_value, enabled):
        self.scene_controller = scene_controller
        self.scene_id = scene_id
        self.trigger_id = trigger_id
        self.trigger_subtype = trigger_subtype
        self.trigger_value = trigger_value
        self.enabled = enabled

        self.stopped = False

    def exec(self):
        raise NotImplementedError

    @background
    def run(self):
        self.exec()

    def info(self):
        return {
            "trigger_type": self.__class__.__name__,
            "trigger_id": self.trigger_id,
            "trigger_subtype": self.trigger_subtype,
            "trigger_value": self.trigger_value,
            "enabled": self.enabled
        }
