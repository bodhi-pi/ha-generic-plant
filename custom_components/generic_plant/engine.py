from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_time_interval

from .const import (
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
)


@dataclass
class WaterResult:
    ran: bool
    confirmed_on: bool


class PlantEngine:
    """Per-plant engine: periodically evaluates whether to water and executes safely."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self._unsub_timer = None
        self._lock = asyncio.Lock()

    def start(self, interval: timedelta) -> None:
        if self._unsub_timer is not None:
            return
        self._unsub_timer = async_track_time_interval(self.hass, self._tick, interval)

    def stop(self) -> None:
        if self._unsub_timer is not None:
            self._unsub_timer()
            self._unsub_timer = None

    def _get_float_state(self, entity_id: str) -> float | None:
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

    # ---------------------------
    # Freshness / staleness guard
    # ---------------------------
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

    async def _tick(self, now) -> None:
        # Prevent overlapping runs
        async with self._lock:
            await self.evaluate_and_water()

    async def evaluate_and_water(self) -> WaterResult:
        """Evaluate conditions and water if needed."""
        # Auto mode must be enabled
        if not self.entry.options.get(OPT_AUTO_WATER, False):
            return WaterResult(ran=False, confirmed_on=False)

        # Sensor must be fresh (not stale/unavailable)
        if not self._is_fresh_enough():
            return WaterResult(ran=False, confirmed_on=False)

        moisture_entity = self.entry.data[CONF_MOISTURE_ENTITY]
        pump_switch = self.entry.data[CONF_PUMP_SWITCH]

        moisture = self._get_float_state(moisture_entity)
        if moisture is None:
            return WaterResult(ran=False, confirmed_on=False)

        threshold = float(self.entry.options.get(OPT_THRESHOLD, DEFAULT_THRESHOLD))
        if moisture >= threshold:
            return WaterResult(ran=False, confirmed_on=False)

        if not self._cooldown_ok():
            return WaterResult(ran=False, confirmed_on=False)

        duration_s = int(self.entry.options.get(OPT_PUMP_DURATION_S, DEFAULT_PUMP_DURATION_S))
        return await self._run_pump(pump_switch, duration_s)

    async def _run_pump(self, pump_switch: str, duration_s: int) -> WaterResult:
        """Turn pump on, confirm ON, set last_watered, run duration, then turn off."""
        await self.hass.services.async_call(
            "switch", "turn_on", {"entity_id": pump_switch}, blocking=True
        )

        confirmed = await self._wait_for_state(pump_switch, "on", timeout_s=5)

        # Only stamp last_watered if the pump actually reported ON
        if confirmed:
            now_iso = datetime.now(timezone.utc).isoformat()
            self.hass.config_entries.async_update_entry(
                self.entry,
                options={**self.entry.options, OPT_LAST_WATERED: now_iso},
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