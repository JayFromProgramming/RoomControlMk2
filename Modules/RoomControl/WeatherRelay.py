import datetime
import math
import os
import time

from pyowm.owm import OWM
from openmeteopy import OpenMeteo
from openmeteopy.hourly import HourlyForecast
from openmeteopy.options import ForecastOptions
from threading import Thread
import geocoder

import requests

from loguru import logger as logging

from Modules.RoomControl import background
from Modules.RoomModule import RoomModule
import pickle

# if not os.path.exists("Cache/map"):
#     os.makedirs("Cache/map")
# for tile in radar_tiles:
#     link = "https://api.maptiler.com/maps/basic-v2/256/{z}/{x}/{y}.png?key=JgtKARiEDXV810p1nbSH"
#     tile_url = link.format(z=6, x=tile[0], y=tile[1])
#     logging.info(f"Getting map tile {tile_url}")
#     image = requests.get(tile_url).content
#     # Save tile image to file
#     with open(f"Cache/map/{tile[0]}-{tile[1]}.png", "wb") as file:
#         file.write(image)
#     logging.info(f"Saved map tile {tile[0]} {tile[1]}")

radar_index_url = "https://api.rainviewer.com/public/weather-maps.json"
radar_base_url = "{host}/{path}/{size}/6/{x}/{y}/{color}/{options}.png"
radar_tiles = [(x, y) for x in range(13, 21) for y in range(21, 25)]


class WeatherRelay(RoomModule):

    def __init__(self, room_controller):
        super().__init__(room_controller)
        self.database = room_controller.database
        self.init_database()
        api_key = self.database.get_table("secrets").get_row(secret_name="openweathermap")["secret_value"]
        self.owm = OWM(api_key)
        self.mgr = self.owm.weather_manager()

        self.actual_location = None
        self.current_weather = None
        self.current_reference_time = None
        self.forecast = None
        # self.location_address = "Milford, MI"
        # self.location_latlong = (42.5903, -83.5983)
        self.location_address = geocoder.ip('me').address
        self.location_latlong = geocoder.ip('me').latlng
        logging.info(f"Location: {self.location_address} {self.location_latlong}")
        self.last_update = 0
        self.parsed_forecast = None
        self.hourly_forecast = HourlyForecast()
        self.forecast_options = ForecastOptions(self.location_latlong[0], self.location_latlong[1])
        self.openmeteo = OpenMeteo(self.forecast_options, self.hourly_forecast.all())
        if os.path.exists("Cache/forecast.pkl"):
            with open("Cache/forecast.pkl", "rb") as file:
                self.forecast = pickle.load(file)
                self.last_update = time.time()
                # self.forecast.last_update = time.time()
                logging.info(f"Loaded forecast from cache {len(self.forecast)}")
        if self.forecast is None:
            # self.openmeteo.get_pandas()
            self.forecast = self.openmeteo.get_dict()
            self.forecast['acquired'] = time.time()
            logging.info(f"Loaded forecast for {len(self.forecast)} hourly forecasts"
                         f" from the API")
            os.makedirs("Cache", exist_ok=True)
            pickle.dump(self.forecast, open("Cache/forecast.pkl", "wb"))
            # self.forecast.last_update = time.time()

        self.radar_fetch_background()
        self.update_current_weather()
        self.update_forecast()
        self.parsed_forecast = self.rebuild_forecast()

    @background
    def update_forecast(self):
        logging.info("Starting forecast update thread")
        while True:
            try:
                if time.time() - self.last_update > 1200:
                    logging.info("Updating forecast")
                    # self.openmeteo.get_pandas()
                    self.forecast = self.openmeteo.get_dict()
                    self.forecast['acquired'] = time.time()
                    self.last_update = time.time()
                    self.parsed_forecast = self.rebuild_forecast()
                    pickle.dump(self.forecast, open("Cache/forecast.pkl", "wb"))
                    # logging.info(f"Updated forecast for {self.forecast.reference_time(timeformat='iso')}")
                else:
                    logging.info(f"Forecast is up to date: {time.time() - self.last_update:.2f}s")
            except Exception as e:
                logging.exception(e)
                logging.error("Error updating forecast")
            finally:
                time.sleep(300)

    @background
    def update_current_weather(self):
        while True:
            try:
                logging.debug("Checking for new weather data")
                if self.location_latlong is None:
                    logging.error("Failed to acquire location data")
                    continue
                observation = self.mgr.weather_at_coords(self.location_latlong[0], self.location_latlong[1])
                self.current_weather = observation.weather
                self.actual_location = observation.location
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
        self.database.create_table("radar_tiles", {
            "timestamp": "integer", "x": "integer", "y": "integer", "color": "integer", "options": "text",
            "image": "blob"
        }, primary_keys=["timestamp", "x", "y", "color"])
        self.database.run("CREATE INDEX IF NOT EXISTS radar_timestamp_index ON radar_tiles (timestamp)")

    def process_probability(self, probability):
        if probability is None:
            return 0
        if "1h" in probability:
            return probability["1h"]
        else:
            return None

    def fetch_radar_tile(self, timestamp, host, path, x, y, color, is_nowcast=False):
        # Check if we already have saved this timestamp in the database
        result = self.database.run("SELECT * FROM radar_tiles WHERE timestamp = ? AND x = ? AND y = ? AND color = ?",
                                   (timestamp, x, y, color)).fetchone()
        time.sleep(0)  # Force a context switch to prevent starvation of other threads
        if result and is_nowcast:
            # Check if this nowcast was fetched within the last 10 minutes and skip if it was
            if time.time() - float(result[4]) < 600:
                logging.debug(f"Skipping nowcast tile {timestamp} {x} {y} {color}")
                return
            logging.debug(f"Updating nowcast tile {timestamp} {x} {y} {color}")
            # Delete the old tile from the database
            self.database.run("DELETE FROM radar_tiles WHERE timestamp = ? AND x = ? AND y = ? AND color = ?",
                              (timestamp, x, y, color))
        elif result:  # Check if we already have this tile
            if result[4] is not None:
                # logging.info(f"Replacing old tile {timestamp} {x} {y} {color}")
                self.database.run("DELETE FROM radar_tiles WHERE timestamp = ? AND x = ? AND y = ? AND color = ?",
                                  (timestamp, x, y, color))
            else:
                return
        tile_url = radar_base_url.format(host=host, path=path, size=512, x=x, y=y,
                                         color=color, options="0_0")
        tile = requests.get(tile_url).content
        time.sleep(0)
        # Add tile saving duplication for debugging a full database
        self.database.run("INSERT INTO radar_tiles (timestamp, x, y, color, image, options) VALUES (?, ?, ?, ?, ?, ?)",
                          (timestamp, x, y, color, tile, time.time() if is_nowcast else None))
        time.sleep(0.5)

    def fetch_radar_imagery(self):

        radar_data = requests.get(radar_index_url).json()
        host = radar_data["host"]
        past = radar_data["radar"]["past"]
        nowcast = radar_data["radar"]["nowcast"]
        logging.info(f"Getting radar imagery from {host}")
        start_time = time.time()
        for tile in radar_tiles:
            for frame in past:
                self.fetch_radar_tile(frame['time'], host, frame['path'], tile[0], tile[1], 4)
        logging.info(f"Finished getting past radar imagery: {time.time() - start_time:.2f}s")
        past_time = time.time()
        for tile in radar_tiles:
            for frame in nowcast:
                self.fetch_radar_tile(frame['time'], host, frame['path'], tile[0], tile[1], 4, is_nowcast=True)
        logging.info(f"Finished getting nowcast radar imagery: {time.time() - past_time:.2f}s")
        logging.info(f"Total time taken: {time.time() - start_time:.2f}s")

    def prune_radar_cache(self):
        # Clear the radar tiles that are older than 7 days
        size = self.database.run("SELECT SUM(LENGTH((image))) FROM radar_tiles").fetchone()[0]
        count = self.database.run("SELECT COUNT(*) FROM radar_tiles").fetchone()[0]
        logging.info(f"Current radar tile cache size: {size / 1024 / 1024:.2f}MB ({count} tiles)")
        results = self.database.run("DELETE FROM radar_tiles WHERE timestamp < ?", (time.time() - 604800,))
        logging.info(f"Deleted {results.rowcount} old radar tiles")
        size = self.database.run("SELECT SUM(LENGTH((image))) FROM radar_tiles").fetchone()[0]
        logging.info(f"Pruned radar tile cache size: {size / 1024 / 1024:.2f}MB")

    @background
    def radar_fetch_background(self):
        while True:
            try:
                self.fetch_radar_imagery()
                self.prune_radar_cache()
            except Exception as e:
                logging.exception(e)
                logging.warning("Aborting radar fetch, retrying in 10 minutes")
            finally:
                time.sleep(600)  # 10 minutes

    def get_available_radar(self):
        # Return the distinct timestamps from the radar_tiles table
        result = self.database.run("SELECT DISTINCT timestamp FROM radar_tiles")
        return [row[0] for row in result.fetchall()]

    def get_radar_tile(self, timestamp, x, y, color):
        result = self.database.run("SELECT image "
                                   "FROM radar_tiles WHERE timestamp = ? AND x = ? AND y = ? AND color = ?",
                                   (timestamp, x, y, color)).fetchone()
        # Check if something was returned
        if not result:
            return None
        return result[0]

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

    def rebuild_forecast(self):
        # When received the forecast is formatted as a dictionary of lists with each list containing a datapoint for that
        # hour. This function will rebuild the forecast into a dictionary of dictionaries with each dictionary containing 1 hour
        # of forecast data
        logging.info("Rebuilding forecast data structure")
        forecast = {}
        data_lists = []  # list of lists of forecast data
        for key in self.forecast['hourly']:
            data_lists.append((key, self.forecast['hourly'][key]))
        for i in range(len(self.forecast['hourly']['time'])):
            forecast[self.forecast['hourly']['time'][i]] = {}
            for data_list in data_lists:
                forecast[self.forecast['hourly']['time'][i]].update({data_list[0]: data_list[1][i]})
            forecast[self.forecast['hourly']['time'][i]]['acquisition_time'] = \
                self.forecast['acquired'] if 'acquired' in self.forecast else None
        return forecast

    def get_available_forecast(self):
        """
        Returns the available forecast data
        :return:
        """
        forecasts = []
        if self.parsed_forecast is None:
            return forecasts
        for key in self.parsed_forecast:
            forecasts.append(key)
            # forecasts.append(int(datetime.datetime.fromisoformat(key).timestamp()))
        return forecasts

    def get_forecast(self, forecast_time):
        """
        Returns the forecast for the given time
        :param forecast_time: The time to get the forecast for
        :return: The forecast for the given time
        """

        for key, forecast in self.parsed_forecast.items():
            # if forecast_time == int(datetime.datetime.fromisoformat(key).timestamp()):
            #     return forecast
            if forecast_time == key:
                return forecast
        logging.error(f"Forecast not found for {forecast_time}")
        return None
