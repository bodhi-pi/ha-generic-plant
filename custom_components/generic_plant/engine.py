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
    PLANT_MODE,
    MODE_AUTO,
    MODE_SENSOR,
    MODE_MANUAL,
    OPT_AUTO_WATER,
    OPT_THRESHOLD,
    OPT_PUMP_DURATION_S,
    OPT_COOLDOWN_MIN,
    OPT_LAST_WATERED,
    OPT_LAST_SEEN,
    OPT_STALE_AFTER_MIN,
    OPT_WATER_INTERVAL_DAYS,
    DEFAULT_THRESHOLD,
    DEFAULT_PUMP_DURATION_S,
    DEFAULT_COOLDOWN_MIN,
    DEFAULT_STALE_AFTER_MIN,
    DEFAULT_WATER_INTERVAL_DAYS,
    OPT_NOTIFY_SERVICE,
    OPT_NOTIFY_ON_WATER,
    OPT_NOTIFY_ON_STALE,
    OPT_NOTIFY_ON_FAILURE,
    OPT_LAST_STALE_NOTIFY,
    OPT_LAST_FAILURE_NOTIFY,
    OPT_LAST_EVALUATED,
    OPT_LAST_DECISION,
    OPT_WATERING_EVENT,
    OPT_LAST_WATER_NOTIFY,

)
from .util import cfg


@dataclass
class WaterResult:
    ran: bool
    confirmed_on: bool


# --------------------------
# Notification helpers
# --------------------------
def _split_notify_service(svc: str) -> tuple[str, str] | None:
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
        async with self._lock:
            await self.evaluate_and_water()

    # ---- option helpers ----
    def _update_options(self, **updates) -> None:
        self.hass.config_entries.async_update_entry(
            self.entry,
            options={**self.entry.options, **updates},
        )

    def _set_decision(self, decision: str) -> None:
        self._update_options(**{OPT_LAST_DECISION: decision})

    def _touch_evaluated(self) -> None:
        self._update_options(**{OPT_LAST_EVALUATED: _now_iso()})

    async def _spike_watering_event(self) -> None:
        """Write 100 then 0 with a short delay so recorder captures both states."""
        self._update_options(**{OPT_WATERING_EVENT: 100})
        await asyncio.sleep(5400)  # 90 minutes — ensures capture at 2 points/hour sampling
        self._update_options(**{OPT_WATERING_EVENT: 0})

    # ---- state helpers ----
    def _mode(self) -> str:
        return self.entry.options.get(PLANT_MODE, MODE_AUTO)

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

    def _get_last_seen(self) -> datetime | None:
        raw = self.entry.options.get(OPT_LAST_SEEN)
        if not raw:
            return None
        try:
            return datetime.fromisoformat(raw)
        except Exception:
            return None

    def _is_fresh_enough(self) -> bool:
        last_seen = self._get_last_seen()
        if last_seen is None:
            return False
        stale_after = int(self.entry.options.get(OPT_STALE_AFTER_MIN, DEFAULT_STALE_AFTER_MIN))
        return (datetime.now(timezone.utc) - last_seen) <= timedelta(minutes=stale_after)

    # ---- main evaluation ----
    async def evaluate_and_water(self) -> WaterResult:
        plant_name = self.entry.data.get(CONF_PLANT_NAME, "Plant")
        mode = self._mode()

        self._touch_evaluated()

        # --- Manual mode: schedule-based, no sensor ---
        if mode == MODE_MANUAL:
            return await self._evaluate_manual(plant_name)

        # --- Sensor-based modes (auto + sensor_only): freshness check first ---
        if not self._is_fresh_enough():
            self._set_decision("skipped_stale_or_unavailable")

            if bool(self.entry.options.get(OPT_NOTIFY_ON_STALE, False)):
                if not _should_throttle(self.entry, OPT_LAST_STALE_NOTIFY, minutes=120):
                    await _send_notify(
                        self.hass,
                        self.entry,
                        enabled_key=OPT_NOTIFY_ON_STALE,
                        title=f"🌱 {plant_name} sensor stale",
                        message="No fresh readings. Watering is blocked until readings resume.",
                    )
                    self._update_options(**{OPT_LAST_STALE_NOTIFY: _now_iso()})

            return WaterResult(ran=False, confirmed_on=False)

        # Clear stale throttle on recovery
        if OPT_LAST_STALE_NOTIFY in self.entry.options:
            new_opts = dict(self.entry.options)
            new_opts.pop(OPT_LAST_STALE_NOTIFY, None)
            self.hass.config_entries.async_update_entry(self.entry, options=new_opts)

        # --- Sensor-only mode: dashboard tracking only. No pump, no cooldown,
        # no notify_on_water, no last_watered/watering_event side effects —
        # there is nothing being watered, so nothing here is allowed to look
        # like a watering decision. ---
        if mode == MODE_SENSOR:
            return self._evaluate_sensor_only()

        # From here down: MODE_AUTO only.
        if not self.entry.options.get(OPT_AUTO_WATER, False):
            self._set_decision("skipped_auto_off")
            return WaterResult(ran=False, confirmed_on=False)

        moisture_entity = cfg(self.entry, CONF_MOISTURE_ENTITY)
        if not moisture_entity:
            self._set_decision("skipped_no_moisture_entity")
            return WaterResult(ran=False, confirmed_on=False)

        moisture = self._get_float_state(moisture_entity)
        if moisture is None:
            self._set_decision("skipped_no_moisture_value")
            return WaterResult(ran=False, confirmed_on=False)

        threshold = float(self.entry.options.get(OPT_THRESHOLD, DEFAULT_THRESHOLD))
        if moisture >= threshold:
            self._set_decision("skipped_above_threshold")
            return WaterResult(ran=False, confirmed_on=False)

        # A plant with no pump_switch configured can never reach a "watered"
        # decision or fire notify_on_water — check this before cooldown so a
        # misconfigured pump-less plant reads as "skipped_no_pump_switch",
        # not a rotating "skipped_cooldown" that looks like it's alive.
        pump_switch = cfg(self.entry, CONF_PUMP_SWITCH)
        if not pump_switch:
            self._set_decision("skipped_no_pump_switch")
            return WaterResult(ran=False, confirmed_on=False)

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

    # ---- mode-specific execution ----
    async def _evaluate_manual(self, plant_name: str) -> WaterResult:
        """Schedule-based evaluation for plants with no sensor."""
        interval_days = float(self.entry.options.get(OPT_WATER_INTERVAL_DAYS, DEFAULT_WATER_INTERVAL_DAYS))
        last_watered = self._get_last_watered()

        if last_watered is not None:
            overdue = (datetime.now(timezone.utc) - last_watered) > timedelta(days=interval_days)
        else:
            overdue = True

        if not overdue:
            self._set_decision("skipped_not_overdue")
            return WaterResult(ran=False, confirmed_on=False)

        if not self._cooldown_ok():
            self._set_decision("skipped_cooldown")
            return WaterResult(ran=False, confirmed_on=False)

        if _should_throttle(self.entry, OPT_LAST_WATER_NOTIFY, minutes=1440):
            self._set_decision("skipped_notify_throttle")
            return WaterResult(ran=False, confirmed_on=False)

        if last_watered:
            days_since = (datetime.now(timezone.utc) - last_watered).days
            message = f"Last watered {days_since} day(s) ago. Time to water!"
        else:
            message = "No watering recorded yet. Time to water!"

        await _send_notify(
            self.hass,
            self.entry,
            enabled_key=OPT_NOTIFY_ON_WATER,
            title=f"🌱 {plant_name} needs water",
            message=message,
        )

        self._update_options(**{OPT_LAST_WATER_NOTIFY: _now_iso()})
        self._set_decision("notified_overdue")

        return WaterResult(ran=False, confirmed_on=False)


    def _evaluate_sensor_only(self) -> WaterResult:
        """Sensor_only mode: read moisture for the dashboard and stop.

        Deliberately does not touch OPT_LAST_WATERED, OPT_WATERING_EVENT, or
        notify_on_water — this mode has no pump, so nothing here should ever
        be able to look like a completed watering. Cooldown does not apply
        either: cooldown throttles *pump* actuation, and there is none.
        """
        moisture_entity = cfg(self.entry, CONF_MOISTURE_ENTITY)
        if not moisture_entity:
            self._set_decision("skipped_no_moisture_entity")
            return WaterResult(ran=False, confirmed_on=False)

        moisture = self._get_float_state(moisture_entity)
        if moisture is None:
            self._set_decision("skipped_no_moisture_value")
            return WaterResult(ran=False, confirmed_on=False)

        threshold = float(self.entry.options.get(OPT_THRESHOLD, DEFAULT_THRESHOLD))
        if moisture < threshold:
            self._set_decision("sensor_only_below_threshold")
        else:
            self._set_decision("sensor_only_above_threshold")

        return WaterResult(ran=False, confirmed_on=False)

    # ---- pump execution (auto mode only) ----
    async def _run_pump(
        self,
        *,
        plant_name: str,
        pump_switch: str,
        duration_s: int,
        moisture: float,
        threshold: float,
    ) -> WaterResult:
        await self.hass.services.async_call(
            "switch", "turn_on", {"entity_id": pump_switch}, blocking=True
        )

        confirmed = await self._wait_for_state(pump_switch, "on", timeout_s=5)

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

        if confirmed:
            self._update_options(**{OPT_LAST_WATERED: _now_iso()})
            self._set_decision("watered")
            await self._spike_watering_event()
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
