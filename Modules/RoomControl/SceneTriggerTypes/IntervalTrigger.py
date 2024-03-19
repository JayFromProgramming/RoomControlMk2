import datetime
import time

from loguru import logger as logging

from Modules.RoomControl.SceneTriggerTypes.SceneTrigger import SceneTrigger


class IntervalTrigger(SceneTrigger):

    default_trigger_subtype = "daily"
    default_trigger_value = "00:00"

    def __init__(self, scene_controller, scene_id, trigger_id, trigger_subtype, trigger_value, enabled):
        super().__init__(scene_controller, scene_id, trigger_id, trigger_subtype, trigger_value, enabled)
        logging.info(f"Initializing IntervalTrigger[{self.trigger_id}] for Scene ({scene_id})")

    def _prep_interval_trigger(self, interval_type: str, interval_value: str):
        """
        Prepares a timer trigger
        :param interval_type: The type of interval trigger (daily, weekly, hourly)
        :param interval_value: The time of day to trigger the scene either in the format WD*:HH:MM or WD*:HH:MM:SS
        """
        match interval_type:
            case "weekly":
                datetime_format = "%w:%H:%M"
            case "daily":
                datetime_format = "%H:%M"
            case "hourly":
                datetime_format = "%M:%S"
            case _:
                logging.error(f"TimerTrigger[{self.trigger_id}] for Scene ({self.scene_id}) has an invalid interval "
                              f"type ({interval_type})")
                return

        # Parse the interval value
        try:
            interval_time = datetime.datetime.strptime(interval_value, datetime_format)
            # The interval time will 1900-01-01 plus whatever the interval rate will be so we need to add the current date
            # to the interval time
            interval_time = datetime.datetime.combine(datetime.datetime.now().date(), interval_time.time())

        except ValueError:
            logging.error(f"TimerTrigger[{self.trigger_id}] for Scene ({self.scene_id}) has an"
                          f" invalid interval value ({interval_value})")
            return

        # Get the current time
        now = datetime.datetime.now()

        # Calculate the time delta between now and the trigger time
        match interval_type:
            case "weekly":
                # If the trigger time is before now then add 7 days to the trigger time
                if interval_time < now:
                    interval_time += datetime.timedelta(days=7)
                # Calculate the time delta
                time_delta = interval_time - now
            case "daily":
                # If the trigger time is before now then add 1 day to the trigger time
                if interval_time < now:
                    interval_time += datetime.timedelta(days=1)
                # Calculate the time delta
                time_delta = interval_time - now
            case "hourly":
                # If the trigger time is before now then however many hours have gone by today
                interval_time += datetime.timedelta(hours=now.hour)
                if interval_time < now:
                    interval_time += datetime.timedelta(hours=1)
                # Calculate the time delta
                time_delta = interval_time - now
            case _:
                time_delta = 0
                logging.error(f"TimerTrigger[{self.trigger_id}] for Scene ({self.scene_id})"
                              f" has an invalid interval type ({interval_type})")

        # Return the time delta in seconds
        return time_delta.total_seconds()

    def exec(self):
        while not self.stopped:
            wait = self._prep_interval_trigger(self.trigger_subtype, self.trigger_value)
            logging.info(f"TimerTrigger[{self.trigger_id}] for Scene ({self.scene_id}) will trigger in {wait} seconds")
            time.sleep(wait)  # Sleep this trigger until the target time arrives
            if self.enabled and not self.stopped:
                logging.info(f"TimerTrigger[{self.trigger_id}] for Scene ({self.scene_id}) has elapsed")
                self.scene_controller.execute_scene(self.scene_id)
            else:
                logging.info(f"TimerTrigger[{self.trigger_id}] for Scene ({self.scene_id})"
                             f" elapsed but trigger was disabled")
        logging.info(f"TimerTrigger[{self.trigger_id}] for Scene ({self.scene_id}) has been stopped")


