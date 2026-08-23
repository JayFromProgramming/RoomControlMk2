"""Room control module for Midea air conditioners, backed by msmart-ng.

Control and state come from msmart-ng. Token retrieval comes from midea-local,
because msmart-ng omits the applianceCodes field that the MSmartHome cloud
requires and therefore fails getToken with error 3004. midea-local sends it and
returns candidate token/key pairs for each udpid derivation, which are then
verified against the appliance before being stored.

Persistence follows the VoiceMonkeyAPI pattern. The secrets table holds only
the Midea account credentials, which are API wide. Everything per appliance
(identifier, address, token and key) lives in the midea_devices table created
by init_database.

Every capability the appliance reports is surfaced. Feature availability is
resolved once at attach time against the device's own supports_* flags, so
unsupported attributes are omitted from the state cache entirely rather than
reported as permanently false.

State is polled at 1 Hz. Energy reporting is decimated because each energy
field is a separate request to the appliance, and the Wi-Fi module handles a
limited number of round trips per second before it starts dropping responses.

While the appliance is powered on, the vertical louvre is held fixed: vertical
swing is disabled and the vertical louvre angle is driven to
LOUVRE_ENFORCED_ANGLE. Corrections are rate limited because the appliance takes
several refresh cycles to reflect an applied change.

Connection attempts run in this order:
    1. Token and key already stored in midea_devices. No cloud contact.
    2. Cloud bootstrap via midea-local for rows missing a token.
    3. Unicast discovery against each stored address.
    4. Limited broadcast discovery across the subnet.
"""

import asyncio
import datetime
import enum

import aiohttp
from midealocal.cloud import get_midea_cloud
from msmart.device import AirConditioner
from msmart.discover import Discover

from Modules.RoomModule import RoomModule
from Modules.RoomObject import RoomObject
from loguru import logger as logging

BROADCAST_ADDRESS = "255.255.255.255"
DEVICE_PORT = 6444

CLOUD_NAME = "SmartHome"

DISCOVERY_TIMEOUT_SECONDS = 5
DISCOVERY_PACKET_COUNT = 3
DISCOVERY_RETRY_SECONDS = 30
DISCOVERY_IDLE_SECONDS = 300

REFRESH_INTERVAL_SECONDS = 1
ENERGY_REFRESH_DIVISOR = 30
COMMAND_COALESCE_SECONDS = 0.2

FAN_SPEED_AUTO = 102

LOUVRE_ENFORCED_ANGLE = 100
LOUVRE_ENFORCE_COOLDOWN_SECONDS = 15

# Optional data groups. Enabling these makes the appliance report the extended
# diagnostic and energy payloads on refresh. Not all firmware honours them.
DATA_REQUEST_FLAGS = (
    "enable_energy_usage_requests",
    "enable_group1_data_requests",
    "enable_group2_data_requests",
    "enable_group5_data_requests",
    "enable_group7_data_requests",
    "enable_group11_data_requests",
)

# Features that may exist under more than one attribute name. The deprecated
# aliases (eco_mode, freeze_protection_mode, flash_cool) are deliberately
# excluded; only turbo still has two genuinely distinct variants.
DUAL_NAMED_FEATURES = {
    "eco_mode": (("eco", "supports_eco"),),
    "frost_protection": (("freeze_protection", "supports_freeze_protection"),),
    "turbo": (("turbo", "supports_turbo"), ("turbo_mode", "supports_turbo_mode")),
}

# Writable comfort and convenience features. Mapping is
# cache key -> (attribute name, support flag or None if always present).
OPTIONAL_FEATURES = {
    "breeze_away": ("breeze_away", "supports_breeze_away"),
    "breeze_mild": ("breeze_mild", "supports_breeze_mild"),
    "breezeless": ("breezeless", "supports_breezeless"),
    "ieco": ("ieco", "supports_ieco"),
    "purifier": ("purifier", "supports_purifier"),
    "out_silent": ("out_silent", "supports_out_silent"),
    "cascade_mode": ("cascade_mode", "supports_cascade"),
    "rate_select": ("rate_select", None),
    "aux_mode": ("aux_mode", None),
    "fresh_air_fan_speed": ("fresh_air_fan_speed", "supports_fresh_air"),
    "target_humidity": ("target_humidity", "supports_target_humidity"),
    "horizontal_swing_angle": ("horizontal_swing_angle", "supports_horizontal_swing_angle"),
    "vertical_swing_angle": ("vertical_swing_angle", "supports_vertical_swing_angle"),
    "horizontal_louvers_angle": ("horizontal_louvers_angle", None),
    "vertical_louvers_angle": ("vertical_louvers_angle", None),
    "display_on": ("display_on", "supports_display_control"),
    "sleep_mode": ("sleep", None),
    "follow_me": ("follow_me", None),
    "beep": ("beep", None),
    "flash": ("flash", "supports_flash"),
    "fahrenheit": ("fahrenheit", None),
}

# Read only sensors and status flags. No support flags exist for most of these,
# so availability is decided by whether the attribute exists at all.
DIAGNOSTIC_ATTRIBUTES = {
    "compressor_frequency": "compressor_frequency",
    "target_compressor_frequency": "target_compressor_frequency",
    "compressor_current": "compressor_current",
    "compressor_voltage": "compressor_voltage",
    "indoor_fan_speed_actual": "indoor_fan_speed",
    "outdoor_fan_speed_actual": "outdoor_fan_speed",
    "target_indoor_fan_speed": "target_indoor_fan_speed",
    "outdoor_unit_power": "outdoor_unit_power",
    "defrost_active": "defrost_active",
    "water_pump_running": "water_pump_running",
    "self_clean_active": "self_clean_active",
    "filter_alert": "filter_alert",
}

# Diagnostics reported in Celsius, converted to Fahrenheit for the room schema.
DIAGNOSTIC_TEMPERATURES = {
    "indoor_coil_temperature": "indoor_coil_temperature",
    "outdoor_coil_temperature": "outdoor_coil_temperature",
    "discharge_pipe_temperature": "discharge_pipe_temperature",
}

# Energy reporting moved from properties to coroutines, so these are method
# names rather than attribute names and each call is its own round trip.
ENERGY_METHODS = {
    "current_energy_usage": "get_current_energy_usage",
    "total_energy_usage": "get_total_energy_usage",
    "real_time_power_usage": "get_real_time_power_usage",
}

# Capability flags worth reporting so the front end can hide controls the
# appliance does not implement. Deprecated aliases are excluded.
CAPABILITY_FLAGS = (
    "supports_eco",
    "supports_turbo",
    "supports_turbo_mode",
    "supports_freeze_protection",
    "supports_breeze_away",
    "supports_breeze_mild",
    "supports_breezeless",
    "supports_cascade",
    "supports_custom_fan_speed",
    "supports_display_control",
    "supports_filter_reminder",
    "supports_flash",
    "supports_fresh_air",
    "supports_horizontal_swing_angle",
    "supports_humidity",
    "supports_ieco",
    "supports_out_silent",
    "supports_purifier",
    "supports_self_clean",
    "supports_target_humidity",
    "supports_vertical_swing_angle",
)


class MideaAPI(RoomModule):
    """Discovers Midea air conditioners and exposes them as room objects."""

    requires_async = True

    def __init__(self, room_controller):
        """Prepare the device table and load stored appliances.

        No network activity happens here. Connection attempts are made by the
        tasks started in start().
        """
        super().__init__(room_controller)
        self.room_controller = room_controller
        self.database = room_controller.database
        self.init_database()

        self.devices = []
        self.stored_appliances = self.load_stored_appliances()
        logging.info(f"MideaAPI: Loaded {len(self.stored_appliances)} stored appliance(s)")

    def init_database(self):
        """Create the midea_devices table if it does not already exist."""
        self.database.create_table(
            "midea_devices",
            {
                "device_id": "TEXT",
                "device_name": "TEXT",
                "address": "TEXT",
                "token": "TEXT",
                "device_key": "TEXT",
            },
        )

    def wait_for_ready(self):
        """Satisfy the module interface; this module connects asynchronously."""
        pass

    async def start(self):
        """Spawn the discovery and refresh tasks on the shared event loop."""
        logging.info("Starting MideaAPI event loop")
        asyncio.create_task(self.begin_device_discovery(), name="MideaDeviceDiscovery")
        asyncio.create_task(self.refresh_device_data(), name="MideaDataRefresher")

    async def begin_device_discovery(self):
        """Connect devices, retrying quickly while none are online."""
        logging.info("Beginning periodic Midea device discovery")
        while True:
            online_count = len([device for device in self.devices if device.online])
            if online_count == 0:
                await self.discover_devices()
                await asyncio.sleep(DISCOVERY_RETRY_SECONDS)
            else:
                await asyncio.sleep(DISCOVERY_IDLE_SECONDS)

    async def discover_devices(self):
        """Connect to stored appliances using the cheapest method that works."""
        try:
            connected_any = False

            for stored_appliance in self.stored_appliances:
                device = await self.connect_stored_appliance(stored_appliance)
                if device is not None:
                    self.register_device(device)
                    connected_any = True

            if connected_any:
                return

            logging.warning("MideaAPI: No stored appliance connected, running discovery")
            for discovered_device in await self.run_discovery():
                self.register_device(discovered_device)
        except Exception as discovery_error:
            logging.error(f"Error discovering Midea devices: {discovery_error}")
            logging.exception(discovery_error)

    # ------------------------------------------------------------------
    # Device table persistence
    # ------------------------------------------------------------------

    def load_stored_appliances(self):
        """Read every row of midea_devices into plain dictionaries.

        Returns:
            A list of dicts with device_id, device_name, address, token and key.
        """
        stored_appliances = []
        cursor = self.database.cursor()
        for stored_row in cursor.execute(
            "SELECT device_id, device_name, address, token, device_key FROM midea_devices"
        ).fetchall():
            stored_appliances.append(
                {
                    "device_id": stored_row[0],
                    "device_name": stored_row[1],
                    "address": stored_row[2],
                    "token": stored_row[3],
                    "key": stored_row[4],
                }
            )
        return stored_appliances

    def save_appliance(self, device):
        """Insert or update the midea_devices row for a connected appliance.

        Args:
            device: A connected msmart-ng AirConditioner.
        """
        device_table = self.database.get_table("midea_devices")
        existing_row = device_table.get_row(device_id=str(device.id))

        if existing_row:
            existing_row.set(
                address=str(device.ip),
                token=str(device.token),
                device_key=str(device.key),
            )
        else:
            cursor = self.database.cursor()
            cursor.execute(
                "INSERT INTO midea_devices "
                "(device_id, device_name, address, token, device_key) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    str(device.id),
                    str(device.name or device.id),
                    str(device.ip),
                    str(device.token),
                    str(device.key),
                ),
            )

        self.refresh_stored_appliance(device)
        logging.info(f"MideaAPI: Saved credentials for device {device.id}")

    def refresh_stored_appliance(self, device):
        """Keep the in memory appliance list in step with the device table.

        Args:
            device: A connected msmart-ng AirConditioner.
        """
        for stored_appliance in self.stored_appliances:
            if stored_appliance["device_id"] == str(device.id):
                stored_appliance["address"] = str(device.ip)
                stored_appliance["token"] = str(device.token)
                stored_appliance["key"] = str(device.key)
                return

        self.stored_appliances.append(
            {
                "device_id": str(device.id),
                "device_name": str(device.name or device.id),
                "address": str(device.ip),
                "token": str(device.token),
                "key": str(device.key),
            }
        )

    # ------------------------------------------------------------------
    # Cloud credential handling
    # ------------------------------------------------------------------

    def cloud_account(self):
        """Return the stored (account, password) pair, or None if absent.

        These are API wide credentials, so they remain in the secrets table.
        """
        secrets_table = self.database.get_table("secrets")
        account_row = secrets_table.get_row(secret_name="MideaUsername")
        password_row = secrets_table.get_row(secret_name="MideaPassword")
        if not account_row or not password_row:
            return None
        return account_row["secret_value"], password_row["secret_value"]

    async def fetch_cloud_credentials(self, device_id):
        """Fetch candidate token and key pairs using midea-local's cloud client.

        midea-local sends the applianceCodes field that the MSmartHome cloud
        requires, and returns one candidate per udpid derivation. Only one will
        authenticate against the appliance, so all are returned for the caller
        to try in turn.

        Args:
            device_id: Numeric appliance identifier as a string or integer.

        Returns:
            A list of (token, key) tuples, empty if the fetch failed.
        """
        account_details = self.cloud_account()
        if account_details is None:
            logging.error("MideaAPI: No cloud account stored, cannot fetch token")
            return []

        account, password = account_details
        try:
            async with aiohttp.ClientSession() as session:
                cloud = get_midea_cloud(CLOUD_NAME, session, account, password)
                if not await cloud.login():
                    logging.error(f"MideaAPI: Login to {CLOUD_NAME} cloud failed")
                    return []

                logging.info(f"MideaAPI: Logged in to {CLOUD_NAME} cloud")
                candidate_keys = await cloud.get_cloud_keys(int(device_id))
        except Exception as cloud_error:
            logging.error(f"MideaAPI: Cloud credential fetch failed: {cloud_error}")
            return []

        candidates = []
        for method, credentials in sorted(candidate_keys.items()):
            logging.info(f"MideaAPI: Cloud returned candidate credentials for method {method}")
            candidates.append((credentials["token"], credentials["key"]))

        if not candidates:
            logging.error(f"MideaAPI: Cloud returned no credentials for device {device_id}")
        return candidates

    # ------------------------------------------------------------------
    # LAN connection and discovery
    # ------------------------------------------------------------------

    async def connect_stored_appliance(self, stored_appliance):
        """Connect to one stored appliance, fetching credentials only if needed.

        Args:
            stored_appliance: A dict from load_stored_appliances.

        Returns:
            A connected AirConditioner, or None on failure.
        """
        device_id = stored_appliance["device_id"]
        address = stored_appliance["address"]

        if stored_appliance["token"] and stored_appliance["key"]:
            device = await self.connect_with_credentials(
                address, device_id, stored_appliance["token"], stored_appliance["key"]
            )
            if device is not None:
                self.save_appliance(device)
                return device
            logging.warning(f"MideaAPI: Stored token rejected for {device_id}, refreshing")

        for token, key in await self.fetch_cloud_credentials(device_id):
            device = await self.connect_with_credentials(address, device_id, token, key)
            if device is not None:
                self.save_appliance(device)
                return device
            logging.warning(f"MideaAPI: Candidate credentials rejected for {device_id}")

        return None

    async def connect_with_credentials(self, address, device_id, token, key):
        """Build and authenticate a device directly from known credentials.

        Args:
            address: IPv4 address of the air conditioner.
            device_id: Numeric device identifier as a string.
            token: Authentication token.
            key: Authentication key (K1).

        Returns:
            A connected AirConditioner, or None if the connection failed.
        """
        try:
            device = AirConditioner(
                ip=address,
                port=DEVICE_PORT,
                device_id=int(device_id),
            )
            await device.authenticate(token, key)
            self.enable_extended_data(device)
            await device.get_capabilities()
            await device.refresh()
        except Exception as connection_error:
            logging.warning(f"MideaAPI: Direct connection to {address} failed: {connection_error}")
            return None

        if not device.online:
            logging.warning(f"MideaAPI: Device at {address} authenticated but reports offline")
            return None

        logging.info(f"MideaAPI: Connected to {device.id} at {address}")
        return device

    @staticmethod
    def enable_extended_data(device):
        """Request the optional diagnostic and energy data groups.

        Args:
            device: An authenticated msmart-ng AirConditioner.
        """
        for request_flag in DATA_REQUEST_FLAGS:
            if not hasattr(device, request_flag):
                continue
            try:
                setattr(device, request_flag, True)
            except Exception as flag_error:
                logging.debug(f"MideaAPI: Could not set {request_flag}: {flag_error}")

    async def run_discovery(self):
        """Discover appliances, trying stored addresses before broadcasting.

        Note that msmart-ng authenticates against the legacy cloud during
        discovery, so these paths may fail even when the midea-local bootstrap
        above succeeds.

        Returns:
            A list of supported AirConditioner objects, possibly empty.
        """
        for stored_appliance in self.stored_appliances:
            address = stored_appliance["address"]
            if not address:
                continue
            try:
                single_device = await Discover.discover_single(
                    address,
                    timeout=DISCOVERY_TIMEOUT_SECONDS,
                    discovery_packets=DISCOVERY_PACKET_COUNT,
                )
            except Exception as unicast_error:
                logging.warning(f"MideaAPI: Unicast discovery at {address} failed: {unicast_error}")
                continue

            if single_device is not None:
                return self.accept_discovered([single_device])

        logging.warning("MideaAPI: Falling back to broadcast discovery")
        try:
            discovered = await Discover.discover(
                target=BROADCAST_ADDRESS,
                timeout=DISCOVERY_TIMEOUT_SECONDS,
                discovery_packets=DISCOVERY_PACKET_COUNT,
            )
        except Exception as broadcast_error:
            logging.error(f"MideaAPI: Broadcast discovery failed: {broadcast_error}")
            return []

        return self.accept_discovered(discovered)

    def accept_discovered(self, discovered):
        """Filter discovery results to supported air conditioners and store them.

        Args:
            discovered: Iterable of device objects returned by msmart-ng.

        Returns:
            A list of supported AirConditioner objects.
        """
        air_conditioners = []
        for candidate_device in discovered:
            if not isinstance(candidate_device, AirConditioner):
                logging.info(f"MideaAPI: Ignoring non air conditioner {candidate_device.id}")
                continue
            if not candidate_device.supported:
                logging.warning(f"MideaAPI: Device {candidate_device.id} reports unsupported")
                continue
            self.enable_extended_data(candidate_device)
            air_conditioners.append(candidate_device)
            self.save_appliance(candidate_device)

        logging.info(f"MideaAPI: Discovery returned {len(air_conditioners)} air conditioner(s)")
        return air_conditioners

    def register_device(self, device):
        """Attach a newly connected device, or refresh an existing one's handle.

        Args:
            device: A connected msmart-ng AirConditioner.
        """
        for existing_device in self.devices:
            if existing_device.device_id != str(device.id):
                continue
            if existing_device.device.ip != device.ip:
                logging.info(
                    f"Midea device {existing_device.device_id} changed address from "
                    f"{existing_device.device.ip} to {device.ip}"
                )
            existing_device.replace_device(device)
            return

        room_device = MideaDevice(device, self.room_controller)
        self.devices.append(room_device)
        asyncio.create_task(
            room_device.send_commands(),
            name=f"MideaCommandSender-{device.id}",
        )
        logging.info(f"Discovered new Midea device {device.id} at {device.ip}")

    def get_device(self, device_id):
        """Return the room object for a device identifier, or None.

        Args:
            device_id: Numeric appliance identifier as a string.
        """
        for room_device in self.devices:
            if room_device.device_id == str(device_id):
                return room_device
        return None

    def get_all_devices(self):
        """Return every attached Midea room object."""
        return self.devices

    async def refresh_device_data(self):
        """Poll every known device once per refresh interval."""
        while True:
            for room_device in self.devices:
                try:
                    await room_device.refresh_info()
                except Exception as refresh_error:
                    logging.error(
                        f"Error refreshing Midea device {room_device.device_id}: {refresh_error}"
                    )
                    logging.exception(refresh_error)
            await asyncio.sleep(REFRESH_INTERVAL_SECONDS)


class MideaDevice(RoomObject):
    """Room object wrapper around a single msmart-ng air conditioner."""

    is_promise = False

    class Modes(enum.IntEnum):
        """Operating modes, with values matching msmart-ng's OperationalMode."""

        UNKNOWN = 0
        AUTO = 1
        COOL = 2
        DRY = 3
        HEAT = 4
        FAN = 5

    @staticmethod
    def celsius_to_fahrenheit(celsius):
        """Convert Celsius to Fahrenheit, passing None through unchanged."""
        if celsius is None:
            return None
        return round(celsius * 9 / 5 + 32, 1)

    @staticmethod
    def fahrenheit_to_celsius(fahrenheit):
        """Convert Fahrenheit to Celsius, passing None through unchanged."""
        if fahrenheit is None:
            return None
        return (fahrenheit - 32) * 5 / 9

    def __init__(self, device, room_controller):
        """Wrap a connected device, resolve its capabilities and register it.

        Args:
            device: A connected msmart-ng AirConditioner.
            room_controller: The owning room controller.
        """
        RoomObject.__init__(self, str(device.id), "MideaDevice")
        self.device = device
        self.device_id = str(device.id)
        self.device_type = "MideaDevice"
        logging.info(f"Creating MideaDevice {self.device_id}@{device.ip}")

        self.device_command_queue = asyncio.Queue()
        self.device_state_cache = {
            "on": False,
            "target_temperature": None,
            "indoor_temperature": None,
            "outdoor_temperature": None,
            "mode": self.Modes.UNKNOWN.name,
            "mode_int": 0,
            "fan_speed": 0,
            "fan_auto": False,
            "vertical_swing": False,
            "horizontal_swing": False,
            "error_code": 0,
            "reason": "Not yet updated",
            "last_updated": None,
        }
        self.online = False
        self.refresh_counter = 0

        self.enforce_louvre_position_enabled = True
        self.last_louvre_correction = None

        self.writable_attributes = self.resolve_writable_attributes()
        self.readable_diagnostics = self.resolve_readable_attributes(DIAGNOSTIC_ATTRIBUTES)
        self.readable_temperatures = self.resolve_readable_attributes(DIAGNOSTIC_TEMPERATURES)
        self.readable_energy = self.resolve_readable_attributes(ENERGY_METHODS)

        self.supported_actions = ["on", "target_value", "mode", "fan_speed", "fan_auto"]
        self.supported_actions.extend(sorted(self.writable_attributes))

        logging.info(
            f"MideaDevice {self.device_id} resolved "
            f"{len(self.writable_attributes)} writable feature(s), "
            f"{len(self.readable_diagnostics) + len(self.readable_temperatures)} diagnostic(s), "
            f"{len(self.readable_energy)} energy field(s)"
        )

        room_controller.attach_object(self)

    def resolve_writable_attributes(self):
        """Determine which writable features this appliance actually supports.

        Features with more than one variant resolve to whichever the device
        reports support for. Features with no support flag are included when
        the attribute exists at all.

        Returns:
            A dict of cache key to msmart-ng attribute name.
        """
        writable_attributes = {}

        for cache_key, candidates in DUAL_NAMED_FEATURES.items():
            for attribute_name, support_flag_name in candidates:
                if getattr(self.device, support_flag_name, False):
                    writable_attributes[cache_key] = attribute_name
                    break

        for cache_key, feature_definition in OPTIONAL_FEATURES.items():
            attribute_name, support_flag_name = feature_definition
            if not hasattr(self.device, attribute_name):
                continue
            if support_flag_name is not None and not getattr(
                self.device, support_flag_name, False
            ):
                continue
            writable_attributes[cache_key] = attribute_name

        return writable_attributes

    def resolve_readable_attributes(self, attribute_map):
        """Determine which read only attributes or methods this appliance has.

        Args:
            attribute_map: Dict of cache key to msmart-ng attribute or method.

        Returns:
            A dict containing only the entries the device implements.
        """
        readable_attributes = {}
        for cache_key, attribute_name in attribute_map.items():
            if hasattr(self.device, attribute_name):
                readable_attributes[cache_key] = attribute_name
        return readable_attributes

    def replace_device(self, device):
        """Swap in a freshly connected device object, keeping cached state.

        Args:
            device: A newly connected AirConditioner for the same appliance.
        """
        self.device = device
        logging.info(f"MideaDevice {self.device_id} reconnected at {device.ip}")

    async def read_energy_value(self, method_name):
        """Call an energy reporting coroutine, returning None if unavailable.

        Args:
            method_name: Name of the msmart-ng energy accessor to call.
        """
        energy_method = getattr(self.device, method_name, None)
        if energy_method is None:
            return None
        try:
            return self.coerce_value(await energy_method())
        except Exception as energy_error:
            logging.debug(f"Energy read {method_name} failed: {energy_error}")
            return None

    async def refresh_info(self):
        """Poll the appliance, rebuild the state cache and enforce louvre position.

        Energy fields are read only every ENERGY_REFRESH_DIVISOR cycles, since
        each is a separate request and the appliance is polled at 1 Hz.
        """
        try:
            await self.device.refresh()
        except Exception as refresh_error:
            self.online = False
            self.device_state_cache["reason"] = str(refresh_error)
            self.device_state_cache["last_updated"] = None
            logging.error(f"Error refreshing Midea device {self.device_id}: {refresh_error}")
            return

        vertical_enabled, horizontal_enabled = self.swing_flags()
        current_fan_speed = int(self.device.fan_speed)

        refreshed_state = {
            "on": self.device.power_state,
            "target_temperature": self.celsius_to_fahrenheit(self.device.target_temperature),
            "indoor_temperature": self.celsius_to_fahrenheit(self.device.indoor_temperature),
            "outdoor_temperature": self.celsius_to_fahrenheit(self.device.outdoor_temperature),
            "indoor_humidity": getattr(self.device, "indoor_humidity", None),
            "mode": self.mode_name(self.device.operational_mode),
            "mode_int": int(self.device.operational_mode or 0),
            "fan_speed": current_fan_speed,
            "fan_auto": current_fan_speed == FAN_SPEED_AUTO,
            "vertical_swing": vertical_enabled,
            "horizontal_swing": horizontal_enabled,
            "error_code": self.device.error_code,
            "reason": "OK",
            "last_updated": datetime.datetime.now().isoformat(),
        }

        for cache_key, attribute_name in self.writable_attributes.items():
            refreshed_state[cache_key] = self.coerce_value(
                getattr(self.device, attribute_name, None)
            )

        for cache_key, attribute_name in self.readable_diagnostics.items():
            refreshed_state[cache_key] = self.coerce_value(
                getattr(self.device, attribute_name, None)
            )

        for cache_key, attribute_name in self.readable_temperatures.items():
            refreshed_state[cache_key] = self.celsius_to_fahrenheit(
                getattr(self.device, attribute_name, None)
            )

        self.refresh_counter += 1
        if self.refresh_counter % ENERGY_REFRESH_DIVISOR == 0 or not self.device_state_cache.get(
            "last_updated"
        ):
            for cache_key, method_name in self.readable_energy.items():
                refreshed_state[cache_key] = await self.read_energy_value(method_name)
        else:
            for cache_key in self.readable_energy:
                refreshed_state[cache_key] = self.device_state_cache.get(cache_key)

        self.online = self.device.online
        self.device_state_cache = refreshed_state
        self.enforce_louvre_position()

    # ------------------------------------------------------------------
    # Louvre position enforcement
    # ------------------------------------------------------------------

    def louvre_correction_due(self):
        """Return whether enough time has passed to re-issue a louvre correction.

        The appliance takes several refresh cycles to reflect an applied
        change, so corrections are rate limited to avoid queueing the same
        command repeatedly while the previous one is still in flight.
        """
        if self.last_louvre_correction is None:
            return True
        elapsed = datetime.datetime.now() - self.last_louvre_correction
        return elapsed.total_seconds() >= LOUVRE_ENFORCE_COOLDOWN_SECONDS

    def desired_swing_mode_without_vertical(self):
        """Return the swing mode that clears vertical swing but keeps horizontal.

        Returns:
            An AirConditioner.SwingMode value.
        """
        if self.device_state_cache.get("horizontal_swing", False):
            return AirConditioner.SwingMode.HORIZONTAL
        return AirConditioner.SwingMode.OFF

    def enforce_louvre_position(self):
        """Hold the vertical louvre fixed at the enforced angle while running.

        When the appliance is powered on, vertical swing is disabled and the
        vertical louvre angle is driven to LOUVRE_ENFORCED_ANGLE. Corrections
        are only issued for features the appliance reports support for, and
        are rate limited by LOUVRE_ENFORCE_COOLDOWN_SECONDS.
        """
        if not self.enforce_louvre_position_enabled:
            return
        if not self.device_state_cache.get("on", False):
            return

        corrections = {}

        if self.device_state_cache.get("vertical_swing", False):
            corrections["swing_mode"] = self.desired_swing_mode_without_vertical()

        angle_attribute = self.writable_attributes.get("vertical_swing_angle")
        current_angle = self.device_state_cache.get("vertical_swing_angle")
        if angle_attribute is not None and current_angle != LOUVRE_ENFORCED_ANGLE:
            corrections[angle_attribute] = LOUVRE_ENFORCED_ANGLE

        if not corrections:
            return
        if not self.louvre_correction_due():
            return

        logging.info(
            f"MideaDevice {self.device_id} correcting louvre position: {corrections}"
        )
        self.last_louvre_correction = datetime.datetime.now()
        self.queue_state(**corrections)

    # ------------------------------------------------------------------
    # Command handling
    # ------------------------------------------------------------------

    @staticmethod
    def coerce_value(value):
        """Convert enum values to plain data so the state stays serialisable.

        Args:
            value: Any attribute value read from the device.
        """
        if isinstance(value, enum.Enum):
            return int(value.value) if isinstance(value.value, int) else value.name
        return value

    async def send_commands(self):
        """Drain the command queue, coalescing pending changes into one apply.

        The appliance state is re-read immediately before applying, because
        msmart-ng's apply() transmits the entire state rather than only the
        changed attributes. Without the resync a stale power_state would be
        written back, overriding a physical power button press.
        """
        logging.info(f"Starting command queue handler for Midea device {self.device_id}")
        while True:
            try:
                staged_attributes = await self.device_command_queue.get()
                await asyncio.sleep(COMMAND_COALESCE_SECONDS)
                while not self.device_command_queue.empty():
                    staged_attributes.update(self.device_command_queue.get_nowait())

                await self.device.refresh()

                for attribute_name, attribute_value in staged_attributes.items():
                    setattr(self.device, attribute_name, attribute_value)
                await self.device.apply()
                logging.info(f"Applied {staged_attributes} to Midea device {self.device_id}")
            except Exception as command_error:
                logging.error(
                    f"Error sending command to Midea device {self.device_id}: {command_error}"
                )

    def queue_state(self, **attributes):
        """Queue msmart-ng attribute changes to be applied by the command task.

        Args:
            **attributes: msmart-ng device attribute names and their new values.
        """
        self.device_command_queue.put_nowait(dict(attributes))

    def set_feature(self, cache_key, value):
        """Set any resolved optional feature by its cache key.

        Args:
            cache_key: Key from writable_attributes, for example "breezeless".
            value: New value for the feature.
        """
        attribute_name = self.writable_attributes.get(cache_key)
        if attribute_name is None:
            logging.warning(f"Midea device {self.device_id} does not support {cache_key}")
            return
        self.queue_state(**{attribute_name: value})

    def mode_name(self, mode_value):
        """Return the enum name for a raw mode value, or UNKNOWN if unrecognised.

        Args:
            mode_value: Raw operational mode as reported by the device.
        """
        if mode_value is None:
            return self.Modes.UNKNOWN.name
        try:
            return self.Modes(int(mode_value)).name
        except ValueError:
            logging.warning(f"Unrecognised Midea mode value: {mode_value}")
            return self.Modes.UNKNOWN.name

    def swing_flags(self):
        """Return the device's swing mode as vertical and horizontal flags.

        Returns:
            A tuple of (vertical_enabled, horizontal_enabled).
        """
        current_swing = self.device.swing_mode
        vertical_enabled = current_swing in (
            AirConditioner.SwingMode.VERTICAL,
            AirConditioner.SwingMode.BOTH,
        )
        horizontal_enabled = current_swing in (
            AirConditioner.SwingMode.HORIZONTAL,
            AirConditioner.SwingMode.BOTH,
        )
        return vertical_enabled, horizontal_enabled

    def clamp_target_celsius(self, celsius):
        """Clamp a target temperature to the range the appliance reports.

        Args:
            celsius: Requested target temperature in Celsius.

        Returns:
            The clamped temperature, or None if the input was None.
        """
        if celsius is None:
            return None
        minimum_target = getattr(self.device, "min_target_temperature", None)
        maximum_target = getattr(self.device, "max_target_temperature", None)
        if minimum_target is not None:
            celsius = max(celsius, minimum_target)
        if maximum_target is not None:
            celsius = min(celsius, maximum_target)
        return celsius

    # ------------------------------------------------------------------
    # Room controller interface
    # ------------------------------------------------------------------

    def name(self):
        """Return the identifier used by the room controller for this object."""
        return self.device_id

    def get_type(self):
        """Return the room controller type identifier for this object."""
        return self.device_type

    def get_state(self):
        """Return the full cached device state, including optional features."""
        state = dict(self.device_state_cache)
        state.pop("reason", None)
        state.pop("last_updated", None)
        state.pop("error_code", None)
        # Preserved for compatibility with consumers of the previous schema.
        state["turbo_fan"] = state.get("turbo", False)
        return state

    def get_diagnostics(self):
        """Return only the compressor, coil, fan and energy readings."""
        diagnostics = {}
        for cache_key in self.readable_diagnostics:
            diagnostics[cache_key] = self.device_state_cache.get(cache_key)
        for cache_key in self.readable_temperatures:
            diagnostics[cache_key] = self.device_state_cache.get(cache_key)
        for cache_key in self.readable_energy:
            diagnostics[cache_key] = self.device_state_cache.get(cache_key)
        return diagnostics

    def get_capabilities(self):
        """Return the appliance's capability flags and supported enumerations."""
        capabilities = {}
        for capability_flag in CAPABILITY_FLAGS:
            if hasattr(self.device, capability_flag):
                capabilities[capability_flag] = bool(getattr(self.device, capability_flag))

        for enumeration_name in (
            "supported_operation_modes",
            "supported_fan_speeds",
            "supported_swing_modes",
            "supported_rate_selects",
            "supported_aux_modes",
        ):
            supported_values = getattr(self.device, enumeration_name, None)
            if supported_values is None:
                continue
            capabilities[enumeration_name] = [
                getattr(value, "name", str(value)) for value in supported_values
            ]

        capabilities["writable_features"] = sorted(self.writable_attributes)
        capabilities["louvre_enforcement"] = self.enforce_louvre_position_enabled
        capabilities["min_target_temperature"] = self.celsius_to_fahrenheit(
            getattr(self.device, "min_target_temperature", None)
        )
        capabilities["max_target_temperature"] = self.celsius_to_fahrenheit(
            getattr(self.device, "max_target_temperature", None)
        )
        return capabilities

    def get_info(self):
        """Return static identifying information about the device."""
        return {
            "model": "Air conditioner",
            "address": self.device.ip,
            "device_id": self.device_id,
            "serial_number": self.device.sn,
            "protocol_version": getattr(self.device, "version", None),
            "indoor_humidity": self.device_state_cache.get("indoor_humidity"),
            "last_updated": self.device_state_cache.get("last_updated"),
        }

    def get_health(self):
        """Return online status and the most recent fault information."""
        return {
            "online": self.online,
            "fault": bool(self.device_state_cache.get("error_code", 0)),
            "reason": self.device_state_cache.get("reason", "Unknown"),
            "filter_alert": self.device_state_cache.get("filter_alert", False),
            "defrost_active": self.device_state_cache.get("defrost_active", False),
        }

    def set_on(self, on):
        """Turn the air conditioner on or off."""
        self.queue_state(power_state=bool(on))

    @property
    def on(self):
        """Whether the air conditioner is currently running."""
        return self.device_state_cache.get("on", False)

    @on.setter
    def on(self, value):
        """Turn the air conditioner on or off."""
        self.set_on(value)

    @property
    def target_value(self):
        """Target temperature in Fahrenheit."""
        return self.device_state_cache.get("target_temperature")

    @target_value.setter
    def target_value(self, value):
        """Set the target temperature, given a value in Fahrenheit."""
        requested_celsius = self.clamp_target_celsius(self.fahrenheit_to_celsius(value))
        self.queue_state(target_temperature=requested_celsius)

    @property
    def mode(self):
        """Current operating mode name."""
        return self.device_state_cache.get("mode", self.Modes.UNKNOWN.name)

    @mode.setter
    def mode(self, value):
        """Set the operating mode from a mode name or numeric value."""
        try:
            if isinstance(value, str):
                requested_mode = self.Modes[value.upper()].value
            else:
                requested_mode = int(value)
            self.queue_state(operational_mode=AirConditioner.OperationalMode(requested_mode))
        except (KeyError, ValueError) as mode_error:
            logging.error(f"Invalid mode {value} for Midea device {self.device_id}: {mode_error}")

    @property
    def fan_speed(self):
        """Current fan speed, where 102 indicates automatic."""
        return self.device_state_cache.get("fan_speed", 0)

    @fan_speed.setter
    def fan_speed(self, value):
        """Set the fan speed to a percentage or the automatic sentinel value."""
        self.queue_state(fan_speed=int(value))

    @property
    def turbo(self):
        """Whether turbo mode is active."""
        return self.device_state_cache.get("turbo", False)

    @turbo.setter
    def turbo(self, value):
        """Enable or disable turbo mode, if the appliance supports it."""
        self.set_feature("turbo", bool(value))

    @property
    def eco(self):
        """Whether eco mode is active."""
        return self.device_state_cache.get("eco_mode", False)

    @eco.setter
    def eco(self, value):
        """Enable or disable eco mode, if the appliance supports it."""
        self.set_feature("eco_mode", bool(value))

    @property
    def frost_protection(self):
        """Whether freeze protection is active."""
        return self.device_state_cache.get("frost_protection", False)

    @frost_protection.setter
    def frost_protection(self, value):
        """Enable or disable freeze protection, if the appliance supports it."""
        self.set_feature("frost_protection", bool(value))

    @property
    def display_on(self):
        """Whether the appliance's display is lit."""
        return self.device_state_cache.get("display_on", False)

    @display_on.setter
    def display_on(self, value):
        """Turn the appliance's display on or off, if supported."""
        self.set_feature("display_on", bool(value))

    @property
    def sleep_mode(self):
        """Whether sleep mode is active."""
        return self.device_state_cache.get("sleep_mode", False)

    @sleep_mode.setter
    def sleep_mode(self, value):
        """Enable or disable sleep mode, if supported."""
        self.set_feature("sleep_mode", bool(value))

    @property
    def target_humidity(self):
        """Target relative humidity, if the appliance supports humidity control."""
        return self.device_state_cache.get("target_humidity")

    @target_humidity.setter
    def target_humidity(self, value):
        """Set the target relative humidity, if supported."""
        self.set_feature("target_humidity", int(value))

    @property
    def louvre_enforcement(self):
        """Whether the vertical louvre is being held at the enforced angle."""
        return self.enforce_louvre_position_enabled

    @louvre_enforcement.setter
    def louvre_enforcement(self, value):
        """Enable or disable automatic vertical louvre correction."""
        self.enforce_louvre_position_enabled = bool(value)
        logging.info(
            f"MideaDevice {self.device_id} louvre enforcement "
            f"{'enabled' if self.enforce_louvre_position_enabled else 'disabled'}"
        )

    @property
    def swing(self):
        """Current swing state split into vertical and horizontal flags."""
        return {
            "vertical": self.device_state_cache.get("vertical_swing", False),
            "horizontal": self.device_state_cache.get("horizontal_swing", False),
        }

    @swing.setter
    def swing(self, value):
        """Enable or disable swing on both axes."""
        if value:
            requested_swing = AirConditioner.SwingMode.BOTH
        else:
            requested_swing = AirConditioner.SwingMode.OFF
        self.queue_state(swing_mode=requested_swing)