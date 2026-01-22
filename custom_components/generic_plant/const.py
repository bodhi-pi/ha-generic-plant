DOMAIN = "generic_plant"

# Config keys stored in config entries (DON'T change these once config_flow uses them)
CONF_PLANT_NAME = "plant_name"
CONF_MOISTURE_ENTITY = "moisture_entity"
CONF_PUMP_SWITCH = "pump_switch"

# Options keys (stored in entry.options) — these are safe to add anytime
OPT_THRESHOLD = "threshold"
OPT_PUMP_DURATION_S = "pump_duration_s"
OPT_COOLDOWN_MIN = "cooldown_min"
OPT_LAST_WATERED = "last_watered"
OPT_AUTO_WATER = "auto_water"
OPT_NOTIFY_SERVICE = "notify_service"     # e.g. "notify.mobile_app_teds_ipad"
OPT_NOTIFY_ON_WATER = "notify_on_water"   # bool
OPT_STALE_AFTER_MIN = "stale_after_min"

# Defaults
DEFAULT_THRESHOLD = 35.0
DEFAULT_PUMP_DURATION_S = 8
DEFAULT_COOLDOWN_MIN = 240
DEFAULT_STALE_AFTER_MIN = 120

# NEW: optional MQTT heartbeat topic + last_seen timestamp
OPT_HEARTBEAT_TOPIC = "heartbeat_topic"
OPT_LAST_SEEN = "last_seen"
