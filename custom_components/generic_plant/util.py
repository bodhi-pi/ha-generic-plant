from __future__ import annotations

from homeassistant.config_entries import ConfigEntry

def cfg(entry: ConfigEntry, key: str, default=None):
    """Prefer options over data for anything configurable after setup."""
    if key in entry.options:
        return entry.options.get(key, default)
    return entry.data.get(key, default)
