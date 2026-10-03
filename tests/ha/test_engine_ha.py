"""Run the integration inside a real Home Assistant test instance."""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.generic_plant.const import DOMAIN

MOIST = "sensor.corn_moist"
PUMP = "switch.corn_pump"


@pytest.fixture
def rig(hass: HomeAssistant):
    pumps: list[tuple[str, float]] = []
    notes: list[dict] = []

    async def _on(call: ServiceCall) -> None:
        hass.states.async_set(PUMP, "on")
        pumps.append(("on", hass.loop.time()))

    async def _off(call: ServiceCall) -> None:
        hass.states.async_set(PUMP, "off")
        pumps.append(("off", hass.loop.time()))

    async def _notify(call: ServiceCall) -> None:
        notes.append(dict(call.data))

    def _register() -> None:
        hass.services.async_register("switch", "turn_on", _on)
        hass.services.async_register("switch", "turn_off", _off)
        hass.services.async_register("notify", "test_phone", _notify)

    hass.data["_rig"] = _register
    hass.states.async_set(PUMP, "off")
    return pumps, notes


def _entry(**opts) -> MockConfigEntry:
    options = {
        "plant_mode": "auto",
        "plant_name": "Corn",
        "moisture_entity": MOIST,
        "pump_switch": PUMP,
        "auto_water": True,
        "threshold": 33,
        "pump_duration_s": 1,
        "cooldown_min": 1440,
        "stale_after_min": 180,
        "last_seen": dt_util.utcnow().isoformat(),
        "response_window_min": 20,
        "response_min_rise": 4,
        "notify_service": "notify.test_phone",
        "notify_on_water": True,
        "notify_on_failure": True,
    }
    options.update(opts)
    return MockConfigEntry(
        domain=DOMAIN,
        title="Corn",
        data={"plant_name": "Corn", "moisture_entity": MOIST, "pump_switch": PUMP},
        options=options,
    )


async def _setup(hass: HomeAssistant, entry: MockConfigEntry):
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    hass.data["_rig"]()
    return hass.data[DOMAIN][entry.entry_id]["engine"]


async def _tick_minutes(hass: HomeAssistant, freezer, minutes: int, on_minute=None) -> None:
    for m in range(1, minutes + 1):
        freezer.tick(timedelta(seconds=60))
        if on_minute:
            on_minute(m)
        async_fire_time_changed(hass, dt_util.utcnow())
        for _ in range(5):
            await asyncio.sleep(0)


async def _teardown(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_pump_stops_after_duration_not_90_minutes(hass: HomeAssistant, rig):
    pumps, notes = rig
    hass.states.async_set(MOIST, "30")
    entry = _entry(response_window_min=0)
    engine = await _setup(hass, entry)

    await asyncio.wait_for(engine.water_now(), timeout=5)
    await hass.async_block_till_done(wait_background_tasks=False)

    assert [a for a, _ in pumps] == ["on", "off"]
    assert pumps[1][1] - pumps[0][1] < 3
    assert entry.options["watering_event"] == 100
    assert notes and notes[0]["title"] == "🌱 Corn watered"
    await _teardown(hass, entry)


async def test_dry_run_warns_and_next_run_still_happens(hass: HomeAssistant, rig, freezer):
    pumps, notes = rig
    hass.states.async_set(MOIST, "32")
    entry = _entry()
    engine = await _setup(hass, entry)

    task = hass.async_create_task(engine.evaluate_now())
    await _tick_minutes(hass, freezer, 21, lambda m: hass.states.async_set(MOIST, "33" if m % 2 else "32"))
    await task
    await hass.async_block_till_done(wait_background_tasks=False)

    assert entry.options["last_response"]["result"] == "no_response"
    assert [n["title"] for n in notes] == ["⚠️ Corn didn't take water"]
    assert "Check the reservoir" in notes[0]["message"]
    assert hass.states.get("sensor.corn_last_watering_result").state == "no_response"

    pumps.clear()
    notes.clear()
    freezer.tick(timedelta(hours=24))
    hass.states.async_set(MOIST, "31")
    await hass.async_block_till_done(wait_background_tasks=False)
    task = hass.async_create_task(engine.evaluate_now())
    readings = {1: "36", 2: "39", 3: "40"}
    await _tick_minutes(hass, freezer, 4, lambda m: readings.get(m) and hass.states.async_set(MOIST, readings[m]))
    await task
    await hass.async_block_till_done(wait_background_tasks=False)

    assert [a for a, _ in pumps] == ["on", "off"], entry.options["last_decision"]
    assert entry.options["last_response"]["result"] == "took"
    assert [n["title"] for n in notes] == ["🌱 Corn watered"]
    assert "+" in notes[0]["message"]
    await _teardown(hass, entry)


async def test_cooldown_still_limits_retries_while_dry(hass: HomeAssistant, rig, freezer):
    pumps, notes = rig
    hass.states.async_set(MOIST, "32")
    entry = _entry()
    engine = await _setup(hass, entry)

    task = hass.async_create_task(engine.evaluate_now())
    await _tick_minutes(hass, freezer, 21, lambda m: hass.states.async_set(MOIST, "33" if m % 2 else "32"))
    await task
    pumps.clear()

    freezer.tick(timedelta(hours=2))
    hass.states.async_set(MOIST, "31")
    await hass.async_block_till_done(wait_background_tasks=False)
    await asyncio.wait_for(engine.evaluate_now(), timeout=5)
    assert pumps == []
    assert entry.options["last_decision"] == "skipped_cooldown"
    await _teardown(hass, entry)


async def test_stale_sensor_gives_unknown_without_warning(hass: HomeAssistant, rig, freezer):
    pumps, notes = rig
    hass.states.async_set(MOIST, "32")
    entry = _entry()
    engine = await _setup(hass, entry)

    task = hass.async_create_task(engine.evaluate_now())
    await _tick_minutes(hass, freezer, 21)
    await task

    assert entry.options["last_response"]["result"] == "unknown"
    assert notes == []
    await _teardown(hass, entry)
