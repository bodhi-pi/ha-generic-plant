"""Replay real pump runs from Home Assistant history through the verification logic.

Change-point data is transcribed from the HA recorder (America/Chicago). Each
event lists the moisture state in effect at pump start, then every state change
inside the verification window. The replay samples that step function once per
minute, which is what the integration does live.
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

_MODULE_PATH = Path(__file__).resolve().parents[1] / "custom_components" / "generic_plant" / "verify_logic.py"
_spec = importlib.util.spec_from_file_location("verify_logic", _MODULE_PATH)
vl = importlib.util.module_from_spec(_spec)
sys.modules["verify_logic"] = vl
_spec.loader.exec_module(vl)

LILAC = {"window_min": 15, "min_rise": 10}
CORN = {"window_min": 20, "min_rise": 4}
MONSTERA = {"window_min": 720, "min_rise": 2}


def _t(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S")


def replay(start: str, baseline: float, changes: list[tuple[str, float]], params: dict, sample_s: int = 60):
    t0 = _t(start)
    pts = sorted((_t(ts), v) for ts, v in changes)
    pending = vl.ResponseCheck(
        started=t0.timestamp(),
        window_end=(t0 + timedelta(minutes=params["window_min"])).timestamp(),
        baseline=baseline,
    )
    current = baseline
    t = t0
    idx = 0
    while True:
        t = t + timedelta(seconds=sample_s)
        while idx < len(pts) and pts[idx][0] <= t:
            current = pts[idx][1]
            idx += 1
        pending.add_sample(current, fresh=True)
        verdict = pending.evaluate(t.timestamp(), params["min_rise"])
        if verdict:
            return verdict, pending.rise, (t - t0).total_seconds() / 60


LILAC_EVENTS = [
    ("2026-09-23 16:31:01", 20, [("2026-09-23 16:31:43", 74), ("2026-09-23 16:32:44", 54), ("2026-09-23 16:34:44", 51), ("2026-09-23 16:35:44", 50), ("2026-09-23 16:36:44", 49), ("2026-09-23 16:37:44", 48), ("2026-09-23 16:39:44", 47), ("2026-09-23 16:44:44", 46)], "took"),
    ("2026-09-26 11:32:16", 20, [("2026-09-26 11:32:26", 21)], "no_response"),
    ("2026-09-27 11:42:16", 17, [], "no_response"),
    ("2026-09-28 11:46:30", 15, [], "no_response"),
    ("2026-09-29 11:56:30", 13, [("2026-09-29 11:56:39", 14), ("2026-09-29 11:59:37", 13)], "no_response"),
    ("2026-09-30 10:16:46", 12, [("2026-09-30 10:18:37", 53), ("2026-09-30 10:19:37", 50), ("2026-09-30 10:20:37", 48), ("2026-09-30 10:21:38", 47), ("2026-09-30 10:23:37", 46), ("2026-09-30 10:24:38", 45), ("2026-09-30 10:26:37", 44), ("2026-09-30 10:28:39", 43)], "took"),
    ("2026-10-02 12:51:42", 20, [("2026-10-02 12:52:51", 80), ("2026-10-02 12:53:51", 54), ("2026-10-02 12:54:51", 51), ("2026-10-02 12:56:52", 50), ("2026-10-02 12:57:51", 49), ("2026-10-02 12:59:51", 48), ("2026-10-02 13:01:51", 47), ("2026-10-02 13:06:51", 46)], "took"),
]

CORN_EVENT = ("2026-09-30 07:36:30", 32, [("2026-09-30 07:37:18", 36), ("2026-09-30 07:38:18", 39), ("2026-09-30 07:39:19", 40), ("2026-09-30 07:46:19", 39)], "took")

MONSTERA_HOURLY = [24, 24, 24, 24, 25, 25, 25, 25, 26, 26, 26, 26, 27]


@pytest.mark.parametrize("start,baseline,changes,expected", LILAC_EVENTS)
def test_lilac_history(start, baseline, changes, expected):
    verdict, rise, minutes = replay(start, baseline, changes, LILAC)
    assert verdict == expected
    if expected == "took":
        assert minutes <= 3
    else:
        assert rise <= 1


def test_corn_history():
    start, baseline, changes, expected = CORN_EVENT
    verdict, rise, minutes = replay(start, baseline, changes, CORN)
    assert verdict == expected
    assert minutes <= 3


def test_monstera_slow_response_hourly():
    start = _t("2026-09-21 16:01:00")
    changes = [((start + timedelta(hours=i + 1)).strftime("%Y-%m-%d %H:%M:%S"), v) for i, v in enumerate(MONSTERA_HOURLY)]
    verdict, rise, minutes = replay(start.strftime("%Y-%m-%d %H:%M:%S"), 24, changes, MONSTERA)
    assert verdict == "took"
    assert minutes <= 720


def test_monstera_dry_flicker_is_no_response():
    start = _t("2026-10-01 12:00:00")
    changes = [((start + timedelta(minutes=m)).strftime("%Y-%m-%d %H:%M:%S"), 24 if m % 2 else 23) for m in range(1, 720)]
    verdict, rise, _ = replay(start.strftime("%Y-%m-%d %H:%M:%S"), 24, changes, MONSTERA)
    assert verdict == "no_response"
    assert rise <= 0


def test_single_spike_does_not_confirm():
    verdict, rise, _ = replay("2026-10-01 12:00:00", 20, [("2026-10-01 12:01:30", 40), ("2026-10-01 12:02:30", 20)], LILAC)
    assert verdict == "no_response"


def test_stale_sensor_is_unknown():
    pending = vl.ResponseCheck(started=0, window_end=900, baseline=20)
    pending.add_sample(None, fresh=False)
    assert pending.evaluate(1000, 10) == "unknown"


def test_lilac_sequence_warns_each_dry_day_and_recovers():
    results = [replay(start, baseline, changes, LILAC)[0] for start, baseline, changes, _ in LILAC_EVENTS]
    assert results == ["took", "no_response", "no_response", "no_response", "no_response", "took", "took"]
