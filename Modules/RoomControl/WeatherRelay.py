import math
import os
import time

from pyowm.owm import OWM
from threading import Thread

from loguru import logger as logging

from Modules.RoomModule import RoomModule
import pickle


class WeatherRelay(RoomModule):

    def __init__(self, room_controller):
        super().__init__(room_controller)
        self.database = room_controller.database
        self.init_database()
        api_key = self.database.get_table("secrets").get_row(secret_name="openweathermap")["secret_value"]
        self.owm = OWM(api_key)
        self.mgr = self.owm.weather_manager()
        self.current_weather = None
        self.current_reference_time = None
        self.forecast = None
        self.thread = Thread(target=self.update, daemon=True)
        self.thread.start()
        if os.path.exists("Cache/forecast.pkl"):
            with open("Cache/forecast.pkl", "rb") as file:
                self.forecast = pickle.load(file)
                logging.info(f"Loaded forecast from cache {len(self.forecast.forecast_hourly)}")
        if self.forecast is None:
            # self.forecast = self.mgr.one_call(lat=47.112878, lon=-88.564697)
            self.forecast = self.mgr.one_call(lat=42.5751, lon=-83.4882)
            logging.info(f"Loaded forecast for {len(self.forecast.forecast_hourly)} hourly forecasts"
                         f" from the API")
            os.makedirs("Cache", exist_ok=True)
            pickle.dump(self.forecast, open("Cache/forecast.pkl", "wb"))
        self.forecast_thread = Thread(target=self.update_forecast, daemon=True)
        self.forecast_thread.start()

    def update_forecast(self):
        while True:
            try:
                if time.time() - getattr(self.forecast, "last_update", 0) > 720:
                    logging.info("Updating forecast")
                    self.forecast = self.mgr.one_call(lat=42.5751, lon=-83.4882)
                    self.forecast.last_update = time.time()
                    pickle.dump(self.forecast, open("Cache/forecast.pkl", "wb"))
                    # logging.info(f"Updated forecast for {self.forecast.reference_time(timeformat='iso')}")
                    logging.info(f"Loaded {len(self.forecast.forecast_hourly)} hourly forecasts")
                else:
                    logging.info("Forecast is up to date")
            except Exception as e:
                logging.exception(e)
            finally:
                time.sleep(300)

    def update(self):
        while True:
            try:
                logging.debug("Checking for new weather data")
                observation = self.mgr.weather_at_place("Commerce Charter Township, Michigan, US")
                self.current_weather = observation.weather
                # Check if the there is a newer weather report
                self.save_current_weather()
                logging.debug(f"Updated weather for {self.current_weather.reference_time(timeformat='iso')}")
            except Exception as e:
                logging.exception(e)
            finally:
                time.sleep(90)

    def init_database(self):
        self.database.create_table("weather_records", {
            "timestamp": "integer", "weather_code": "integer",
            "temperature": "real", "feels": "real", "humidity": "real",
            "wind_speed": "real", "wind_direction": "real", "wind_gust": "real",
            "status": "text", "secondary_status": "text",
            "visibility": "real", "chance": "real", "rain": "real", "snow": "real", "clouds": "real"
        }, primary_keys=["timestamp"])

    def process_probability(self, probability):
        if probability is None:
            return 0
        if "1h" in probability:
            return probability["1h"]
        else:
            return 0

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
            rain = self.process_probability(self.current_weather.rain)
            snow = self.process_probability(self.current_weather.snow)
            clouds = self.current_weather.clouds or 0
            updated = self.current_weather.reference_time()
            probability = self.current_weather.precipitation_probability
            table = self.database.get_table("weather_records")
            table.add(timestamp=updated, weather_code=weather_code,
                      temperature=temp['temp'], feels=temp['feels_like'], humidity=humidity,
                      wind_speed=wind_speed, wind_direction=wind_direction, wind_gust=wind_gust,
                      status=status, chance=probability,
                      secondary_status=secondary_status, visibility=visibility, rain=rain, snow=snow,
                      clouds=clouds)
            logging.info(f"Saved weather record for {self.current_weather.reference_time()}")
        except ValueError:
            pass
        except Exception as e:
            logging.error(f"Error saving current weather: {e}")
            logging.exception(e)

    def get_available_forecast(self):
        """
        Returns the available forecast data
        :return:
        """
        forecasts = []
        for forecast in self.forecast.forecast_hourly:
            forecasts.append(forecast.reference_time())
        return forecasts

    def get_forecast(self, forecast_time):
        """
        Returns the forecast for the given time
        :param forecast_time: The time to get the forecast for
        :return: The forecast for the given time
        """

        for forecast in self.forecast.forecast_hourly:
            if forecast.ref_time == int(forecast_time):
                return forecast
