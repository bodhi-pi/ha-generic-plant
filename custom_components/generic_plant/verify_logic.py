"""Pure post-watering response check (no Home Assistant imports).

Moisture is sampled on a fixed cadence after a pump run. The watering counts as
taken when the "sustained peak" (the highest value seen on two consecutive
samples, which ignores one-off spikes and +/-1 sensor flicker) rises at least
`min_rise` points above the pre-pump baseline. If the window ends without that
rise while the sensor kept reporting, the water most likely never arrived.
"""

from __future__ import annotations

from dataclasses import dataclass

RESULT_TOOK = "took"
RESULT_NO_RESPONSE = "no_response"
RESULT_UNKNOWN = "unknown"

MIN_SAMPLES_FOR_NO_RESPONSE = 3


@dataclass
class ResponseCheck:
    started: float
    window_end: float
    baseline: float
    last_sample: float | None = None
    sustained_peak: float | None = None
    samples: int = 0
    sensor_reported: bool = False

    def add_sample(self, value: float | None, *, fresh: bool) -> None:
        if fresh:
            self.sensor_reported = True
        if value is None:
            return
        if self.last_sample is not None:
            pair_floor = min(self.last_sample, value)
            if self.sustained_peak is None or pair_floor > self.sustained_peak:
                self.sustained_peak = pair_floor
        self.last_sample = value
        self.samples += 1

    @property
    def rise(self) -> float | None:
        if self.sustained_peak is None:
            return None
        return self.sustained_peak - self.baseline

    def evaluate(self, now: float, min_rise: float) -> str | None:
        rise = self.rise
        if rise is not None and rise >= min_rise:
            return RESULT_TOOK
        if now < self.window_end:
            return None
        if not self.sensor_reported or self.samples < MIN_SAMPLES_FOR_NO_RESPONSE:
            return RESULT_UNKNOWN
        return RESULT_NO_RESPONSE
