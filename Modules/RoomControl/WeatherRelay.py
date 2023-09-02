import math
import time

from pyowm.owm import OWM
from threading import Thread

from loguru import logger as logging


class WeatherRelay:

    def __init__(self, db):
        self.database = db
        self.init_database()
        api_key = self.database.get_table("secrets").get_row(secret_name="openweathermap")["secret_value"]
        self.owm = OWM(api_key)
        self.mgr = self.owm.weather_manager()
        self.current_weather = None
        self.current_reference_time = None
        self.forecast = None
        self.thread = Thread(target=self.update, daemon=True)
        self.thread.start()

    def update(self):
        while True:
            logging.debug("Checking for new weather data")
            self.current_weather = self.mgr.weather_at_place("Houghton, Michigan, US").weather
            self.forecast = self.mgr.one_call(lat=47.112878, lon=-88.564697)
            if self.current_weather.reference_time() <= self.current_reference_time:
                logging.debug("Reference time has not changed, will check again in 1 minute")
                time.sleep(60)
                continue
            self.current_reference_time = self.current_weather.reference_time()
            self.save_current_weather()
            logging.debug(f"Updated weather for {self.current_weather.reference_time(timeformat='iso')}")
            time.sleep(60)

    def init_database(self):
        self.database.create_table("weather_records", {
            "timestamp": "integer", "weather_code": "integer",
            "temperature": "real", "feels": "real", "humidity": "real",
            "wind_speed": "real", "wind_direction": "real", "wind_gust": "real",
            "status": "text", "secondary_status": "text",
            "visibility": "real", "chance": "real", "rain": "real", "snow": "real", "clouds": "real"
        }, primary_keys=["timestamp"])

    def save_current_weather(self):
        """
        Logs the temperature, humidity, wind speed, and wind direction to the database for the current time
        :return:
        """
        try:
            weather_code = self.current_weather.weather_code
            temp = self.current_weather.temperature('fahrenheit')
            wind = self.current_weather.wind('miles_hour')
            wind_speed = wind['speed'] if 'speed' in wind else None
            wind_direction = wind['deg'] if 'deg' in wind else None
            wind_gust = wind['gust'] if 'gust' in wind else None
            humidity = self.current_weather.humidity
            status = self.current_weather.detailed_status
            secondary_status_list = getattr(self.current_weather, "extra_status_info", [])
            # convert the list of secondary statuses to a comma separated string
            secondary_status = ",".join([status["main"] for status in secondary_status_list])
            visibility = self.current_weather.visibility() if self.current_weather.visibility() < 10000 else math.inf
            rain = self.current_weather.rain or 0
            snow = self.current_weather.snow or 0
            clouds = self.current_weather.clouds or 0
            updated = self.current_weather.reference_time()
            probability = self.current_weather.precipitation_probability
            table = self.database.get_table("weather_records")
            table.update_or_add(timestamp=updated, weather_code=weather_code,
                                temperature=temp['temp'], feels=temp['feels_like'], humidity=humidity,
                                wind_speed=wind_speed, wind_direction=wind_direction, wind_gust=wind_gust,
                                status=status, chance=probability,
                                secondary_status=secondary_status, visibility=visibility, rain=rain, snow=snow,
                                clouds=clouds)
        except Exception as e:
            logging.error(f"Error saving current weather: {e}")
