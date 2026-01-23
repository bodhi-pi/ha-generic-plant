from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_time_interval

from .const import (
    CONF_PLANT_NAME,
    CONF_MOISTURE_ENTITY,
    CONF_PUMP_SWITCH,
    OPT_AUTO_WATER,
    OPT_THRESHOLD,
    OPT_PUMP_DURATION_S,
    OPT_COOLDOWN_MIN,
    OPT_LAST_WATERED,
    OPT_LAST_SEEN,
    OPT_STALE_AFTER_MIN,
    DEFAULT_THRESHOLD,
    DEFAULT_PUMP_DURATION_S,
    DEFAULT_COOLDOWN_MIN,
    DEFAULT_STALE_AFTER_MIN,
    # Notifications
    OPT_NOTIFY_SERVICE,
    OPT_NOTIFY_ON_WATER,
    OPT_NOTIFY_ON_STALE,
    OPT_NOTIFY_ON_FAILURE,
    # Notification throttles
    OPT_LAST_STALE_NOTIFY,
    OPT_LAST_FAILURE_NOTIFY,
    # Diagnostics
    OPT_LAST_EVALUATED,
    OPT_LAST_DECISION,
)

from .util import cfg


# --------------------------
# Internal helper structures
# --------------------------
@dataclass
class WaterResult:
    ran: bool
    confirmed_on: bool


# --------------------------
# Notification helpers
# --------------------------
def _split_notify_service(svc: str) -> tuple[str, str] | None:
    """Parse 'notify.mobile_app_x' -> ('notify','mobile_app_x')."""
    svc = (svc or "").strip()
    if not svc or "." not in svc:
        return None
    domain, name = svc.split(".", 1)
    if domain != "notify" or not name:
        return None
    return domain, name


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _should_throttle(entry: ConfigEntry, last_key: str, *, minutes: int) -> bool:
    """Return True if a notification was sent recently."""
    raw = entry.options.get(last_key)
    if not raw:
        return False
    try:
        last = datetime.fromisoformat(raw)
    except Exception:
        return False
    return (datetime.now(timezone.utc) - last) < timedelta(minutes=minutes)


async def _send_notify(
    hass: HomeAssistant,
    entry: ConfigEntry,
    *,
    enabled_key: str,
    title: str,
    message: str,
) -> None:
    """Send a notify.* message if configured and enabled."""
    notify_service = (entry.options.get(OPT_NOTIFY_SERVICE) or "").strip()
    enabled = bool(entry.options.get(enabled_key, False))
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


# --------------------------
# Engine
# --------------------------
class PlantEngine:
    """Per-plant engine: periodically evaluates whether to water and executes safely."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self._unsub_timer = None
        self._lock = asyncio.Lock()

    # ---- lifecycle ----
    def start(self, interval: timedelta) -> None:
        if self._unsub_timer is not None:
            return
        self._unsub_timer = async_track_time_interval(self.hass, self._tick, interval)

    def stop(self) -> None:
        if self._unsub_timer is not None:
            self._unsub_timer()
            self._unsub_timer = None

    async def _tick(self, now) -> None:
        # Prevent overlapping runs
        async with self._lock:
            await self.evaluate_and_water()

    # ---- option helpers ----
    def _update_options(self, **updates) -> None:
        """Merge updates into entry.options."""
        self.hass.config_entries.async_update_entry(
            self.entry,
            options={**self.entry.options, **updates},
        )

    def _set_decision(self, decision: str) -> None:
        self._update_options(**{OPT_LAST_DECISION: decision})

    def _touch_evaluated(self) -> None:
        self._update_options(**{OPT_LAST_EVALUATED: _now_iso()})

    # ---- state helpers ----
    def _get_float_state(self, entity_id: str) -> float | None:
        if not entity_id:
            return None
        st = self.hass.states.get(entity_id)
        if not st:
            return None
        try:
            return float(st.state)
        except ValueError:
            return None

    def _get_last_watered(self) -> datetime | None:
        raw = self.entry.options.get(OPT_LAST_WATERED)
        if not raw:
            return None
        try:
            return datetime.fromisoformat(raw)
        except Exception:
            return None

    def _cooldown_ok(self) -> bool:
        cd_min = int(self.entry.options.get(OPT_COOLDOWN_MIN, DEFAULT_COOLDOWN_MIN))
        if cd_min <= 0:
            return True
        last = self._get_last_watered()
        if last is None:
            return True
        return (datetime.now(timezone.utc) - last) > timedelta(minutes=cd_min)

    # ---- freshness / staleness guard ----
    def _get_last_seen(self) -> datetime | None:
        raw = self.entry.options.get(OPT_LAST_SEEN)
        if not raw:
            return None
        try:
            return datetime.fromisoformat(raw)
        except Exception:
            return None

    def _is_fresh_enough(self) -> bool:
        """True only when we have a recent reading (prevents watering on stale/unknown data)."""
        last_seen = self._get_last_seen()
        if last_seen is None:
            return False  # unknown -> unsafe

        stale_after = int(self.entry.options.get(OPT_STALE_AFTER_MIN, DEFAULT_STALE_AFTER_MIN))
        return (datetime.now(timezone.utc) - last_seen) <= timedelta(minutes=stale_after)

    # ---- main logic ----
    async def evaluate_and_water(self) -> WaterResult:
        """Evaluate conditions and water if needed."""
        plant_name = self.entry.data.get(CONF_PLANT_NAME, "Plant")

        # Always stamp that we evaluated (even if we do nothing)
        self._touch_evaluated()

        # 1) Sensor freshness check first (independent of Auto Water).
        # This allows stale notifications even if Auto Water is OFF.
        if not self._is_fresh_enough():
            self._set_decision("skipped_stale_or_unavailable")

            if bool(self.entry.options.get(OPT_NOTIFY_ON_STALE, False)):
                if not _should_throttle(self.entry, OPT_LAST_STALE_NOTIFY, minutes=120):
                    await _send_notify(
                        self.hass,
                        self.entry,
                        enabled_key=OPT_NOTIFY_ON_STALE,
                        title=f"🌱 {plant_name} sensor stale",
                        message="No fresh readings. Auto-watering is blocked until readings resume.",
                    )
                    self._update_options(**{OPT_LAST_STALE_NOTIFY: _now_iso()})

            return WaterResult(ran=False, confirmed_on=False)

        # Sensor is fresh now — clear stale notify throttle so a NEW stale episode can notify again.
        if OPT_LAST_STALE_NOTIFY in self.entry.options:
            new_opts = dict(self.entry.options)
            new_opts.pop(OPT_LAST_STALE_NOTIFY, None)
            self.hass.config_entries.async_update_entry(self.entry, options=new_opts)

        # 2) Auto mode must be enabled to actually water
        if not self.entry.options.get(OPT_AUTO_WATER, False):
            self._set_decision("skipped_auto_off")
            return WaterResult(ran=False, confirmed_on=False)

        # Resolve the configured moisture + pump entities (options override data)
        moisture_entity = cfg(self.entry, CONF_MOISTURE_ENTITY)
        pump_switch = cfg(self.entry, CONF_PUMP_SWITCH)

        if not moisture_entity:
            self._set_decision("skipped_no_moisture_entity")
            return WaterResult(ran=False, confirmed_on=False)

        if not pump_switch:
            self._set_decision("skipped_no_pump_switch")
            return WaterResult(ran=False, confirmed_on=False)

        # 3) Must have a numeric moisture value
        moisture = self._get_float_state(moisture_entity)
        if moisture is None:
            self._set_decision("skipped_no_moisture_value")
            return WaterResult(ran=False, confirmed_on=False)

        # 4) Must be below threshold
        threshold = float(self.entry.options.get(OPT_THRESHOLD, DEFAULT_THRESHOLD))
        if moisture >= threshold:
            self._set_decision("skipped_above_threshold")
            return WaterResult(ran=False, confirmed_on=False)

        # 5) Must pass cooldown
        if not self._cooldown_ok():
            self._set_decision("skipped_cooldown")
            return WaterResult(ran=False, confirmed_on=False)

        duration_s = int(self.entry.options.get(OPT_PUMP_DURATION_S, DEFAULT_PUMP_DURATION_S))
        return await self._run_pump(
            plant_name=plant_name,
            pump_switch=pump_switch,
            duration_s=duration_s,
            moisture=moisture,
            threshold=threshold,
        )

    async def _run_pump(
        self,
        *,
        plant_name: str,
        pump_switch: str,
        duration_s: int,
        moisture: float,
        threshold: float,
    ) -> WaterResult:
        """Turn pump on, confirm ON, set last_watered, run duration, then turn off."""
        await self.hass.services.async_call(
            "switch", "turn_on", {"entity_id": pump_switch}, blocking=True
        )

        confirmed = await self._wait_for_state(pump_switch, "on", timeout_s=5)

        # Failure notification (throttled)
        if not confirmed:
            self._set_decision("failed_pump_confirm_on")

            if bool(self.entry.options.get(OPT_NOTIFY_ON_FAILURE, False)):
                if not _should_throttle(self.entry, OPT_LAST_FAILURE_NOTIFY, minutes=60):
                    await _send_notify(
                        self.hass,
                        self.entry,
                        enabled_key=OPT_NOTIFY_ON_FAILURE,
                        title=f"🌱 {plant_name} watering failed",
                        message="Pump did not confirm ON. No last-watered timestamp was written.",
                    )
                    self._update_options(**{OPT_LAST_FAILURE_NOTIFY: _now_iso()})

        # Only stamp last_watered + notify success if pump actually reported ON
        if confirmed:
            now_iso = _now_iso()
            self._update_options(**{OPT_LAST_WATERED: now_iso})
            self._set_decision("watered")

            await _send_notify(
                self.hass,
                self.entry,
                enabled_key=OPT_NOTIFY_ON_WATER,
                title=f"🌱 {plant_name} watered",
                message=(
                    f"Moisture: {moisture:.1f}%\n"
                    f"Threshold: {threshold:.1f}%\n"
                    f"Duration: {int(duration_s)}s"
                ),
            )

        await asyncio.sleep(max(1, int(duration_s)))

        await self.hass.services.async_call(
            "switch", "turn_off", {"entity_id": pump_switch}, blocking=True
        )

        return WaterResult(ran=True, confirmed_on=confirmed)

    async def _wait_for_state(self, entity_id: str, desired: str, timeout_s: int) -> bool:
        st = self.hass.states.get(entity_id)
        if st and st.state == desired:
            return True

        end = self.hass.loop.time() + timeout_s
        while self.hass.loop.time() < end:
            await asyncio.sleep(0.2)
            st = self.hass.states.get(entity_id)
            if st and st.state == desired:
                return True
        return False