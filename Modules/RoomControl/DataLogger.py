import datetime
import time
from loguru import logger as logging

import ConcurrentDatabase
from Modules.RoomControl import background
from Modules.RoomModule import RoomModule


class DataLoggingHost(RoomModule):

    def __init__(self, room_controller):
        super().__init__(room_controller)
        logging.info("DataLoggingHost: Initializing")

        self.room_controller = room_controller
        self.database = room_controller.database
        self.database_init()

        self.loggers = {}
        self.init_all_loggers()

    def database_init(self):
        # cursor = self.database.cursor()
        # cursor.execute("""CREATE TABLE IF NOT EXISTS
        #                 data_sources (name text, source_name text, logging_interval integer, enabled boolean, unit text,
        #                 attribute TEXT DEFAULT NULL, uuid INTEGER PRIMARY KEY AUTOINCREMENT)""")
        self.database.create_table("data_sources",
                                   {"name": "TEXT", "source_name": "TEXT", "logging_interval": "INTEGER",
                                    "enabled": "BOOLEAN", "unit": "TEXT", "attribute": "TEXT DEFAULT NULL",
                                    "uuid": "INTEGER PRIMARY KEY AUTOINCREMENT"})
        # cursor.execute("""CREATE TABLE IF NOT EXISTS
        #                 data_logging (id INTEGER REFERENCES data_sources(uuid),
        #                  timestamp TIMESTAMP, value TEXT, compression_level integer)""")
        self.database.create_table("data_logging", {"id": "INTEGER REFERENCES data_sources(uuid)",
                                                    "timestamp": "TIMESTAMP", "value": "TEXT",
                                                    "compression_level": "INTEGER"})
        # cursor.execute("""CREATE TABLE IF NOT EXISTS
        #                 web_graphing_presets(name text, data_sources text, time_range integer)""")
        self.database.create_table("web_graphing_presets", {"name": "TEXT", "data_sources": "TEXT",
                                                            "time_range": "INTEGER"}, primary_keys=["name"])
        # cursor.close()
        # self.database.commit()

    def init_all_loggers(self):
        logging.info("DataLoggingHost: Initializing all loggers")

        table = self.database.get_table("data_sources")
        sources = table.get_all()

        for source in sources:
            data_source = self.get_source(source['source_name'])
            self.loggers[source['name']] = DataLogger(source['name'], self.database, source=data_source,
                                                      logging_interval=source['logging_interval'],
                                                      enabled=source['enabled'], unit=source['unit'],
                                                      attribute=source['attribute'], uuid=source['uuid'])
        logging.info("DataLoggingHost: All loggers initialized")

    def get_source(self, source_name):
        return self.room_controller.get_object(source_name)

    def get_sources(self):
        return self.loggers.values()

    def get_data(self, source, start_time, end_time):
        """Convert log data into a list of tuples"""
        if source.startswith("weather_"):
            results = self.database.get(f"SELECT timestamp, {source[8:]} "
                                        f"FROM main.weather_records WHERE timestamp >= ? AND timestamp <= ?",
                                        (start_time, end_time))
            data = []
            for row in results:
                data.append((row[0], row[1]))
            return data
        else:
            cursor = self.loggers[source].get_logs(start_time, end_time)
            data = []
            for row in cursor:
                # Generate an ISO 8601 timestamp
                # timestamp = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(row[1]))
                data.append((row[1], row[2]))
            return data

    def get_presets(self):
        presets = self.database.get("SELECT * FROM web_graphing_presets")

        results = {}

        for preset in presets:

            # If the source is not a number but instead a weather_ source then we just want to return the name
            # of the source

            if preset[1] is None:
                sources = self.database.get("SELECT * FROM data_sources")
                sources += ["weather_temperature", "weather_feels", "weather_humidity", "weather_wind_speed"]
            else:
                sources = preset[1].split(",")

            print(sources)
            source_names = []
            for source in sources:
                source_names.append(source)

            results[preset[0]] = {
                "time_range": preset[2],
                "data_sources": source_names
            }

        return results


class DataLogger:

    def __init__(self, name, database, source, logging_interval=30,
                 enabled=True, unit="", attribute=None, uuid=None):
        logging.info(f"DataLogger ({name}): Initializing")
        self.name = name
        self.database = database
        self.table = self.database.get_table("data_logging")
        self.source = source
        self.logging_interval = logging_interval
        self.unit = unit
        self.enabled = True
        self.attribute = attribute
        self.uuid = uuid
        self.senicide()  # Remove old logs
        self.start_logging()

    @background
    def start_logging(self):
        while True:
            try:
                if self.enabled:
                    self.log()
            except Exception as e:
                logging.error(f"DataLogger ({self.name}): {e}")
            finally:
                time.sleep(self.logging_interval)

    def log(self):
        """Log the current value of the data source"""
        if self.attribute is not None:
            if hasattr(self.source, self.attribute):
                if callable(getattr(self.source, self.attribute)):
                    value = getattr(self.source, self.attribute)()
                else:
                    value = getattr(self.source, self.attribute)
            else:
                logging.error(f"DataLogger ({self.name}): Attribute {self.attribute} not found")
                return
        elif hasattr(self.source, "get_value"):
            value = self.source.get_value("current_value")
            if self.source.get_fault():
                logging.error(f"DataLogger ({self.name}): Sensor is faulty")
                return  # Don't log if the sensor is faulty
        else:
            logging.error(f"DataLogger ({self.name}): No attribute or get_value method found")
            return

        timestamp = int(time.time())

        # self.table.add(id=self.uuid, timestamp=timestamp, value=value, compression_level=1)

        self.database.run("INSERT INTO data_logging VALUES (?, ?, ?, ?)", (self.uuid, timestamp, value, 1))

    def get_logs(self, start_time, end_time):
        """Get the logs between the start and end time"""
        start_stamp = datetime.datetime.fromtimestamp(int(start_time)).strftime("%Y-%m-%dT%H:%M:%S")
        end_stamp = datetime.datetime.fromtimestamp(int(end_time)).strftime("%Y-%m-%dT%H:%M:%S")
        logging.info(f"DataLogger ({self.name}): Getting logs between {start_stamp} and {end_stamp}")
        fetch_start = time.time()
        result = self.database.get("SELECT * FROM data_logging WHERE id = ? AND timestamp >= ? AND timestamp <= ?",
                                   (self.uuid, start_time, end_time))

        # result = self.table.get_all(id=self.uuid, timestamp=[start_time, end_time])

        logging.info(f"DataLogger ({self.name}): {len(result)} logs fetched in {time.time() - fetch_start} seconds")
        return result

    def senicide(self):
        """Remove logs older than 4 days"""
        logging.info(f"DataLogger ({self.name}): Removing old logs")
        self.database.run("DELETE FROM data_logging WHERE timestamp < ? AND id = ?",
                          (int(time.time()) - 345600, self.uuid))

        # self.table.delete_many(timestamp=[0, int(time.time()) - 345600], id=self.uuid)
