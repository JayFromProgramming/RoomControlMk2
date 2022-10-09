import time
import logging

from Modules.RoomControl import background

logging = logging.getLogger(__name__)


class DataLoggingHost:

    def __init__(self, database, room_controllers=None, room_sensor_host=None):
        logging.info("DataLoggingHost: Initializing")
        if room_controllers is None:
            room_controllers = []

        self.database = database
        self.database_init()
        self.room_controllers = room_controllers
        self.room_sensor_host = room_sensor_host
        self.all_data_sources = {}

        logging.info("DataLoggingHost: Combining all data sources")
        # Combine all room control devices and sensors into a single list
        for controller in self.room_controllers:
            for device in controller.get_all_devices():
                self.all_data_sources[f"device_{device.name()}"] = device

        for sensor in self.room_sensor_host.get_sensors():
            for sensor_value in sensor.get_sensor_values():
                self.all_data_sources[f"sensor_{sensor_value.get_name()}"] = sensor_value
        logging.info("DataLoggingHost: All data sources combined")
        print(self.all_data_sources)
        self.loggers = {}
        self.init_all_loggers()

    def database_init(self):
        cursor = self.database.cursor()
        cursor.execute("""CREATE TABLE IF NOT EXISTS 
                        data_sources (name text, source_name text, logging_interval integer, enabled boolean, unit text,
                        attribute TEXT DEFAULT NULL, uuid INTEGER PRIMARY KEY AUTOINCREMENT)""")
        cursor.execute("""CREATE TABLE IF NOT EXISTS
                        data_logging (id INTEGER REFERENCES data_sources(uuid),
                         timestamp integer, value TEXT, compression_level integer)""")
        cursor.close()
        self.database.commit()

    def init_all_loggers(self):
        logging.info("DataLoggingHost: Initializing all loggers")
        cursor = self.database.cursor()
        cursor.execute("SELECT * FROM data_sources")
        sources = cursor.fetchall()
        for source in sources:
            data_source = self.get_source(source[1])
            self.loggers[source[0]] = DataLogger(source[0], self.database, source=data_source,
                                                 logging_interval=source[2], enabled=source[3], unit=source[4],
                                                 attribute=source[5], uuid=source[6])
        cursor.close()
        logging.info("DataLoggingHost: All loggers initialized")

    def get_source(self, source_name):
        return self.all_data_sources[source_name]

    def get_sources(self):
        return self.loggers.values()

    def get_data(self, source, start_time, end_time):
        """Convert log data into a list of tuples"""
        cursor = self.loggers[source].get_logs(start_time, end_time)
        data = []
        for row in cursor:
            data.append((row[1], row[2]))
        return data


class DataLogger:

    def __init__(self, name, database, source, logging_interval=30,
                 enabled=True, unit="", attribute=None, uuid=None):
        logging.info(f"DataLogger ({name}): Initializing")
        self.name = name
        self.database = database
        self.source = source
        self.logging_interval = logging_interval
        self.unit = unit
        self.enabled = True
        self.attribute = attribute
        self.uuid = uuid
        self.start_logging()

    @background
    def start_logging(self):
        while True:
            if self.enabled:
                self.log()
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
            value = self.source.get_value()
            if self.source.get_fault():
                return  # Don't log if the sensor is faulty
        else:
            return

        timestamp = int(time.time())

        self.database.run("INSERT INTO data_logging VALUES (?, ?, ?, ?)", (self.uuid, timestamp, value, 1))

    def get_logs(self, start_time, end_time):
        """Get the logs between the start and end time"""
        return self.database.get("SELECT * FROM data_logging WHERE id = ? AND timestamp >= ? AND timestamp <= ?",
                                 (self.uuid, start_time, end_time))
