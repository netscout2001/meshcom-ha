"""Property-based tests of the loaders for stored data (.storage files).

A broken or edited storage file must never break the setup: every entry is
either taken over with valid values or dropped.
"""

from __future__ import annotations

import math
import os
from typing import Any

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from custom_components.meshcom.aiomeshcom import is_callsign
from custom_components.meshcom.chat import _parse as parse_message
from custom_components.meshcom.const import MAX_PATH
from custom_components.meshcom.stations import _parse_station

# Pull requests get the same examples every run (no flaky CI); the weekly
# scheduled run sets MESHCOM_FUZZ=explore and searches randomly and longer.
_EXPLORE = os.environ.get("MESHCOM_FUZZ") == "explore"
FAST = settings(
    max_examples=5000 if _EXPLORE else 300,
    derandomize=not _EXPLORE,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)

_hostile = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(),
    st.floats(),
    st.text(max_size=80),
    st.sampled_from(
        ["QA1ABC-12", "2026-11-09T10:00:00+00:00", "2026-11-09T10:00:00", "dm:QA1ABC-12"]
    ),
    st.lists(
        st.one_of(st.text(max_size=12), st.sampled_from(["QB0AAA-12", "TST1-1"])), max_size=15
    ),
    st.dictionaries(st.text(max_size=5), st.integers(), max_size=3),
)

_STATION = {
    "callsign": "QA1ABC-12",
    "last_heard": "2026-11-09T10:00:00+00:00",
    "rssi": -100,
    "snr": 5.0,
    "hops": 1,
    "battery": 80,
    "latitude": 50.1,
    "longitude": 8.7,
    "firmware": "4.40a",
    "temperature": 4.5,
    "humidity": 90.0,
    "pressure_qnh": 1020.0,
    "pressure_qfe": 960.0,
    "weather_time": "2026-11-09T10:00:00+00:00",
    "path": ["QB0AAA-12"],
}
_MESSAGE = {
    "id": "40000101",
    "conversation": "group:262",
    "sender": "QA1ABC-12",
    "destination": "262",
    "text": "hello",
    "time": "2026-11-09T10:00:00+00:00",
    "own": False,
    "via_server": False,
    "rssi": -100,
    "snr": 5,
    "status": None,
    "path": ["QA1ABC-12", "QB0AAA-12"],
}


def _in(value: float | None, low: float, high: float) -> bool:
    return value is None or (math.isfinite(value) and low <= value <= high)


@given(st.dictionaries(st.sampled_from(sorted(_STATION)), _hostile, max_size=5))
@FAST
def test_stored_station(changes: dict[str, Any]) -> None:
    station = _parse_station({**_STATION, **changes})
    if station is None:
        return
    assert is_callsign(station.callsign)
    assert station.last_heard.tzinfo is not None
    assert _in(station.latitude, -90, 90)
    assert _in(station.longitude, -180, 180)
    assert _in(station.temperature, -60, 85)
    assert _in(station.humidity, 0, 100)
    assert _in(station.pressure_qnh, 800, 1100)
    assert station.battery is None or 0 <= station.battery <= 100
    assert len(station.path) <= MAX_PATH
    assert all(is_callsign(hop) for hop in station.path)
    assert station.firmware is None or len(station.firmware) <= 16


@given(_hostile)
@FAST
def test_stored_station_any_shape(raw: Any) -> None:
    assert _parse_station(raw) is None or isinstance(raw, dict)


@given(st.dictionaries(st.sampled_from(sorted(_MESSAGE)), _hostile, max_size=5))
@FAST
def test_stored_message(changes: dict[str, Any]) -> None:
    message = parse_message({**_MESSAGE, **changes})
    if message is None:
        return
    assert is_callsign(message.sender)
    assert all(is_callsign(hop) for hop in message.path)
    assert len(message.path) <= MAX_PATH
    assert isinstance(message.text, str)
    assert isinstance(message.own, bool)
