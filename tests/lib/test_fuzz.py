"""Property-based fuzz tests of everything that reads untrusted input.

Every parser must either return a valid result or raise its documented
error, never crash in another way. Beyond "no crash", the results must keep
the guarantees the integration relies on: clean text, valid callsigns,
coordinates in range, bounded sizes. Inputs start from the anonymised
capture of real traffic and are mutated, truncated and padded.
"""

from __future__ import annotations

import contextlib
import json
import math
import os
from pathlib import Path
from typing import Any

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from aiomeshcom import (
    InvalidOutgoingError,
    InvalidPacketError,
    PositionPacket,
    TelemetryPacket,
    TextMessagePacket,
    build_text_message,
    is_callsign,
    parse_datagram,
)
from aiomeshcom.builder import validate_text_message
from aiomeshcom.const import (
    MAX_INCOMING_TEXT_CHARS,
    MAX_JSON_KEYS,
    MAX_OUTGOING_TEXT_BYTES,
    MAX_PATH_CHARS,
)
from aiomeshcom.kiss import (
    MAX_KISS_FRAME,
    PORT_DATA,
    KissDecoder,
    KissDeframer,
    _encode_address,
    auth_response,
    kiss_frame,
    parse_nonce,
)
from aiomeshcom.text import clean_text, contains_unwanted
from aiomeshcom.webapi import (
    WebConnectionError,
    parse_groups,
    parse_info_page,
    parse_mheard_page,
)
from aiomeshcom.webpages import (
    parse_node_info,
    parse_position_page,
    parse_rxlog_page,
    parse_update_status,
)
from tests.lib.mheard_html import Card, page
from tests.lib.node_pages_html import info_page, position_page, rxlog_page

FIXTURE = Path(__file__).parent / "fixtures" / "capture_2026-11-06.anon.jsonl"
SAMPLES: list[dict[str, Any]] = [
    json.loads(json.loads(line)["raw"]) for line in FIXTURE.read_text().splitlines() if line
]
# Pull requests get the same examples every run (no flaky CI); the weekly
# scheduled run sets MESHCOM_FUZZ=explore and searches randomly and longer.
_EXPLORE = os.environ.get("MESHCOM_FUZZ") == "explore"
FAST = settings(
    max_examples=5000 if _EXPLORE else 300,
    derandomize=not _EXPLORE,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)

# Values an attacker can put into any JSON field.
_hostile = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(),
    st.floats(),  # includes NaN and +-inf
    st.text(max_size=300),
    st.text(alphabet="\u202e\u200f\u2066\u0000\u001b\ufeff\u00e4A1-,*:{}", max_size=60),
    st.lists(st.integers(), max_size=5),
    st.dictionaries(st.text(max_size=5), st.integers(), max_size=3),
)
_keys = sorted({key for sample in SAMPLES for key in sample} | {"type", "src", "dst", "msg"})


def _check_packet(packet: object) -> None:
    """Guarantees the integration relies on for every parsed packet."""
    path = getattr(packet, "path", None)
    if path is not None:
        assert path.callsigns
        assert all(is_callsign(call) for call in path.callsigns)
        assert len(",".join(path.callsigns)) <= MAX_PATH_CHARS
    if isinstance(packet, TextMessagePacket):
        assert not contains_unwanted(packet.text)
        assert len(packet.text) <= MAX_INCOMING_TEXT_CHARS
    if isinstance(packet, PositionPacket):
        if packet.latitude is not None:
            assert math.isfinite(packet.latitude)
            assert -90 <= packet.latitude <= 90
        if packet.longitude is not None:
            assert math.isfinite(packet.longitude)
            assert -180 <= packet.longitude <= 180
    if isinstance(packet, TelemetryPacket):
        for value in (packet.temperature_1, packet.humidity, packet.pressure_qnh):
            assert value is None or math.isfinite(value)


def _parse(data: bytes) -> None:
    try:
        packet = parse_datagram(data)
    except InvalidPacketError:
        return
    _check_packet(packet)


# --- external UDP -------------------------------------------------------------


@given(st.sampled_from(SAMPLES), st.dictionaries(st.sampled_from(_keys), _hostile, max_size=4))
@FAST
def test_udp_mutated_real_packets(sample: dict[str, Any], changes: dict[str, Any]) -> None:
    """Real packets with hostile values in any field."""
    with contextlib.suppress(ValueError):  # NaN/inf are not encodable as strict JSON
        _parse(json.dumps({**sample, **changes}, allow_nan=False).encode())


@given(st.sampled_from(SAMPLES), st.data())
@FAST
def test_udp_truncated_and_padded(sample: dict[str, Any], data: st.DataObject) -> None:
    """Cut-off, padded and repeated datagrams."""
    raw = json.dumps(sample).encode()
    cut = data.draw(st.integers(0, len(raw)))
    noise = data.draw(st.binary(max_size=64))
    for candidate in (raw[:cut], raw[:cut] + noise, noise + raw, raw * 3):
        _parse(candidate)


@given(st.sampled_from(SAMPLES), st.text(max_size=600))
@FAST
def test_udp_hostile_text(sample: dict[str, Any], text: str) -> None:
    """Arbitrary text in messages ends up clean or is rejected."""
    _parse(json.dumps({**sample, "msg": text}).encode())


@given(st.integers(MAX_JSON_KEYS - 2, MAX_JSON_KEYS + 20))
@settings(max_examples=30, deadline=None)
def test_udp_many_keys(count: int) -> None:
    _parse(json.dumps({f"k{i}": i for i in range(count)} | {"type": "msg"}).encode())


# --- KISS --------------------------------------------------------------------


def _ax25(src: str, info: bytes) -> bytes:
    return (
        _encode_address("APRSMC", last=False, command=True)
        + _encode_address(src, last=True, command=False)
        + b"\x03\xf0"
        + info
    )


@given(st.binary(max_size=3 * MAX_KISS_FRAME))
@FAST
def test_kiss_stream_never_crashes(stream: bytes) -> None:
    """Any byte stream: frames stay bounded, decoding never crashes."""
    deframer = KissDeframer()
    for frame in deframer.feed(stream):
        assert len(frame) <= MAX_KISS_FRAME
    decoder = KissDecoder("QX1YZ-9")
    for packet in [*decoder.feed(stream), *decoder.flush()]:
        _check_packet(packet)


@given(
    st.sampled_from(["TST1-1", "QX1YZ-9", "QB0AAA-12"]),
    st.one_of(
        st.binary(max_size=300),
        st.builds(
            lambda body: f"!{body}".encode(errors="surrogatepass"),
            st.text(alphabet="0123456789.NSEW/\\#>-=ABHTQPOFG", max_size=80),
        ),
        st.builds(lambda text: f":{text}".encode(), st.text(max_size=250)),
    ),
)
@FAST
def test_kiss_hostile_aprs_info(src: str, info: bytes) -> None:
    """Hostile APRS position and message bodies in valid frames."""
    decoder = KissDecoder("QX1YZ-9")
    for packet in [*decoder.feed(kiss_frame(PORT_DATA, _ax25(src, info))), *decoder.flush()]:
        _check_packet(packet)


@given(st.binary(max_size=200))
@FAST
def test_kiss_nonce_line(line: bytes) -> None:
    nonce = parse_nonce(line)
    assert nonce is None or len(nonce) == 16


@given(st.text(max_size=40), st.binary(min_size=16, max_size=16))
@FAST
def test_kiss_auth_response(password: str, nonce: bytes) -> None:
    """Any password: a 64-digit hex answer or a clean rejection."""
    try:
        answer = auth_response(password, nonce)
    except InvalidOutgoingError:
        return
    assert len(answer) == 66
    assert answer.endswith(b"\r\n")
    int(answer[:64], 16)


# --- web API -----------------------------------------------------------------


@given(st.text(max_size=5000))
@FAST
def test_info_page(body: str) -> None:
    _check_info(body)


@given(st.text(alphabet="<>/td FirmwareBatteryMeshcom0123456789.V(%)abc", max_size=400))
@FAST
def test_info_page_near_misses(body: str) -> None:
    """Text close to the real page does not confuse the patterns."""
    _check_info(body)


def _check_info(body: str) -> None:
    firmware, voltage = parse_info_page(body)
    assert firmware is None or (len(firmware) <= 6 and firmware.isascii())
    assert voltage is None or 0 < voltage < 10


def _check_mheard(body: str) -> None:
    entries = parse_mheard_page(body)
    if entries is None:
        return
    assert len(entries) <= 128
    assert len({entry.callsign for entry in entries}) == len(entries)
    for entry in entries:
        assert is_callsign(entry.callsign)
        assert 0 <= entry.age_minutes <= 1440
        assert entry.hardware is None or (entry.hardware.isascii() and "<" not in entry.hardware)
        assert entry.latitude is None or -90 <= entry.latitude <= 90
        assert entry.longitude is None or -180 <= entry.longitude <= 180
        assert entry.rssi is None or -200 <= entry.rssi <= 50


@given(st.text(max_size=600))
@FAST
def test_mheard_page_text(body: str) -> None:
    """Any answer (login page, garbage) gives a list or None, never an error."""
    _check_mheard("MHeard Information" + body)


_CALLS = st.text(alphabet="QRABCXYZ0123456789-<>&;\"' ", min_size=0, max_size=14)
_FIELD = st.text(alphabet="0123456789-. ,abcdefghijklmnopqrstuvwxyzNSEW<>&", max_size=14)


@given(
    st.lists(
        st.builds(
            Card,
            call=_CALLS,
            age_min=st.integers(-5, 100000),
            hw=_FIELD,
            fw=_FIELD,
            rssi=st.none() | st.integers(-10000, 10000),
            snr=st.none() | st.integers(-1000, 1000),
            lat=st.none() | st.floats(-1000, 1000),
            lon=st.none() | st.floats(-1000, 1000),
            alt=st.none() | st.integers(-(10**7), 10**7),
            hm_snr=st.none() | st.integers(-1000, 1000),
            ex=st.integers(0, 10**5),
            nb=st.integers(0, 10**5),
            ncnt=st.integers(0, 10**5),
        ),
        max_size=6,
    ),
    st.integers(0, 4000),
)
@FAST
def test_mheard_page_cards(cards: list[Card], cut: int) -> None:
    """Cards with wild values, the page cut anywhere: only valid values come out."""
    body = page(cards)
    _check_mheard(body)
    _check_mheard(body[: len(body) - cut])


@given(st.text(max_size=600), st.integers(0, 3000))
@FAST
def test_node_pages_text(body: str, cut: int) -> None:
    """Info, position and RX log parsers take any text without an error."""
    for page_body in (info_page(), position_page(), rxlog_page()):
        mixed = page_body[: max(0, len(page_body) - cut)] + body
        info = parse_node_info(mixed)
        assert info.uptime_seconds is None or 0 <= info.uptime_seconds <= 10 * 365 * 86400
        assert info.hardware is None or info.hardware.isascii()
        gps = parse_position_page(mixed)
        assert gps is None or gps.satellites is None or 0 <= gps.satellites <= 64
        radio = parse_rxlog_page(mixed)
        if radio is not None:
            assert 0 <= radio.queue_used <= radio.queue_size
            assert radio.rx_percent is None or 0 <= radio.rx_percent <= 100


_ATTR_VALUE = st.one_of(
    st.integers(-(10**12), 10**12), st.text(alphabet="0123456789-x<>&", max_size=12)
)


@given(
    st.dictionaries(
        st.sampled_from(["ring", "p0", "p1", "p5", "rx", "tx", "int", "win", "bp", "drop", "dwin"]),
        _ATTR_VALUE,
        max_size=8,
    )
)
@FAST
def test_rxlog_attributes(values: dict[str, int | str]) -> None:
    """Wild queue attributes: a consistent result or None."""
    radio = parse_rxlog_page(rxlog_page(**values))
    if radio is not None:
        assert 0 <= radio.queue_used <= radio.queue_size <= 1000
        assert radio.rx_percent is None or 0 <= radio.rx_percent <= 100
        assert radio.tx_percent is None or 0 <= radio.tx_percent <= 100
        assert radio.state in (None, "accepted", "slow_down", "refused")


@given(st.text(max_size=300))
@FAST
def test_group_list(raw: str) -> None:
    try:
        groups = parse_groups(raw)
    except WebConnectionError:
        return
    assert all(group.isdigit() for group in groups)


# --- outgoing and text cleaning ------------------------------------------------


@given(st.text(max_size=20), st.text(max_size=300))
@FAST
def test_outgoing_validation(destination: str, text: str) -> None:
    """Only valid messages pass; what passes builds a small datagram."""
    try:
        validate_text_message(destination, text)
    except InvalidOutgoingError:
        return
    assert len(text.encode()) <= MAX_OUTGOING_TEXT_BYTES
    assert not contains_unwanted(text)
    assert len(build_text_message(destination, text)) < 400


@given(st.text(max_size=500))
@FAST
def test_clean_text_removes_everything_unwanted(value: str) -> None:
    cleaned, changed = clean_text(value)
    assert not contains_unwanted(cleaned)
    assert changed == (cleaned != value)


# --- firmware update state (/austatus) ------------------------------------------

_UPDATE_SAMPLE: dict[str, Any] = {
    "st": "ok",
    "job": "check",
    "run": "v4.40a.11.07",
    "avail": "v4.40a.11.20",
    "newer": 1,
    "inst": 1,
    "staged": "",
    "err": "",
    "pct": 0,
    "phone": 0,
    "sbok": 1,
}


@given(st.dictionaries(st.sampled_from(sorted(_UPDATE_SAMPLE)), _hostile, max_size=5))
@FAST
def test_update_status_mutated(changes: dict[str, Any]) -> None:
    """Any value in any field: None or a status with only safe values."""
    status = parse_update_status({**_UPDATE_SAMPLE, **changes})
    if status is None:
        return
    for tag in (status.running, status.available, status.staged):
        assert tag is None or (tag.isascii() and "<" not in tag and len(tag) <= 23)
    assert status.error is None or status.error.replace("_", "").isalnum()
    assert 0 <= status.percent <= 100
