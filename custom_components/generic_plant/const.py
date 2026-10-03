DOMAIN = "generic_plant"

# Config keys stored in config entries (DON'T change these once config_flow uses them)
CONF_PLANT_NAME = "plant_name"
CONF_MOISTURE_ENTITY = "moisture_entity"
CONF_PUMP_SWITCH = "pump_switch"

# Plant modes
PLANT_MODE = "plant_mode"
MODE_AUTO = "auto"
MODE_SENSOR = "sensor_only"
MODE_MANUAL = "manual"

# Options keys (stored in entry.options) — these are safe to add anytime
OPT_THRESHOLD = "threshold"
OPT_PUMP_DURATION_S = "pump_duration_s"
OPT_COOLDOWN_MIN = "cooldown_min"
OPT_LAST_WATERED = "last_watered"
OPT_AUTO_WATER = "auto_water"
OPT_NOTIFY_SERVICE = "notify_service"
OPT_NOTIFY_ON_WATER = "notify_on_water"
OPT_STALE_AFTER_MIN = "stale_after_min"
OPT_NOTIFY_ON_FAILURE = "notify_on_failure"
OPT_NOTIFY_ON_STALE = "notify_on_stale"
OPT_WATER_INTERVAL_DAYS = "water_interval_days"  # NEW: for manual mode


# Notification throttles
OPT_LAST_STALE_NOTIFY = "last_stale_notify"
OPT_LAST_FAILURE_NOTIFY = "last_failure_notify"
OPT_LAST_WATER_NOTIFY = "last_water_notify"


# Diagnostics (persisted)
OPT_LAST_EVALUATED = "last_evaluated"
OPT_LAST_DECISION = "last_decision"

# Watering event spike sensor (plots as vertical line on graph)
OPT_WATERING_EVENT = "watering_event"


# Defaults
DEFAULT_THRESHOLD = 35.0
DEFAULT_PUMP_DURATION_S = 8
DEFAULT_COOLDOWN_MIN = 240
DEFAULT_STALE_AFTER_MIN = 120
DEFAULT_WATER_INTERVAL_DAYS = 7  # NEW

# MQTT heartbeat
OPT_HEARTBEAT_TOPIC = "heartbeat_topic"
OPT_LAST_SEEN = "last_seen"
