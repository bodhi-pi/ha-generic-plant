from __future__ import annotations

from datetime import datetime, timezone, timedelta

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry


def _split_notify_service(svc: str) -> tuple[str, str] | None:
    svc = (svc or "").strip()
    if not svc or "." not in svc:
        return None
    domain, name = svc.split(".", 1)
    if domain != "notify" or not name:
        return None
    return domain, name


async def send_notify(
    hass: HomeAssistant,
    entry: ConfigEntry,
    title: str,
    message: str,
    *,
    option_notify_service_key: str,
    option_notify_enabled_key: str,
) -> None:
    """Send notification using notify.* service configured in entry.options."""
    notify_service = (entry.options.get(option_notify_service_key) or "").strip()
    enabled = bool(entry.options.get(option_notify_enabled_key, False))
    split = _split_notify_service(notify_service)

    if not enabled or not split:
        return

    domain, service_name = split
    await hass.services.async_call(
        domain,
        service_name,
        {"title": title, "message": message},
        blocking=False,
    )


def should_throttle(entry: ConfigEntry, last_key: str, *, minutes: int) -> bool:
    """Return True if we should suppress a notification because we sent one recently."""
    raw = entry.options.get(last_key)
    if not raw:
        return False
    try:
        last = datetime.fromisoformat(raw)
    except Exception:
        return False
    return (datetime.now(timezone.utc) - last) < timedelta(minutes=minutes)


def mark_notified(entry: ConfigEntry, last_key: str) -> dict:
    """Return new options dict with last_key set to now()."""
    now_iso = datetime.now(timezone.utc).isoformat()
    return {**entry.options, last_key: now_iso}
