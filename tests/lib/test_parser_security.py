"""Abuse cases for the parser (security concept C-01, C-03, C-07, C-08, C-13).

Every datagram reaching the parser may come from any device on the LAN.
"""

from __future__ import annotations

import contextlib
import json
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from aiomeshcom import (
    AckMessagePacket,
    DeliveryStatus,
    DeliveryStatusPacket,
    InvalidPacketError,
    TextMessagePacket,
    parse_datagram,
)

BASE_MSG: dict[str, Any] = {
    "src_type": "lora",
    "type": "msg",
    "src": "TST1-12",
    "dst": "*",
    "msg": "hello",
    "msg_id": "40000ED4",
    "firmware": 40,
    "fw_sub": "a",
    "rssi": -90,
    "snr": 5,
    "hw_id": 3,
    "lora_mod": 8,
    "max_hop": 4,
}

BASE_POS: dict[str, Any] = {
    "src_type": "lora",
    "type": "pos",
    "src": "TST1-12",
    "msg": "",
    "lat": 47.5,
    "lat_dir": "N",
    "long": 11.5,
    "long_dir": "E",
    "aprs_symbol": "-",
    "aprs_symbol_group": "/",
    "hw_id": 12,
    "msg_id": "40000ED3",
    "alt": 1667,
    "lora_mod": 8,
    "max_hop": 2,
    "batt": 96,
    "firmware": 40,
    "fw_sub": "a",
    "rssi": -100,
    "snr": 3,
}


def encode(obj: Any) -> bytes:
    return json.dumps(obj, ensure_ascii=False).encode("utf-8")


def reason(data: bytes) -> str:
    with pytest.raises(InvalidPacketError) as err:
        parse_datagram(data)
    return err.value.reason


def msg(**changes: Any) -> bytes:
    return encode({**BASE_MSG, **changes})


def pos(**changes: Any) -> bytes:
    return encode({**BASE_POS, **changes})


# --- framing and JSON -------------------------------------------------------


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        (b"", "size"),
        (b"{" + b" " * 2000 + b"}", "size"),
        (b"\xff\xfe{}", "encoding"),
        (b"{not json", "json_syntax"),
        (b"[1, 2]", "json_not_object"),
        (b'"text"', "json_not_object"),
        (b'{"type": "msg", "rssi": NaN}', "json_constant"),
        (b'{"type": "msg", "rssi": Infinity}', "json_constant"),
        (b'{"type": "msg", "type": "pos"}', "json_duplicate_key"),
        (b'{"type": "msg", "x": {"y": 1}}', "json_nested"),
        (b'{"type": "msg", "x": [1]}', "json_nested"),
        (b"[" * 500 + b"]" * 500, "json_not_object"),
        (b'{"a":' * 150 + b"1" + b"}" * 150, "json_nested"),
        (b'{"test": 1}', "unknown_type"),
        (b'{"type": "hb", "seq": 1}', "unknown_type"),
        (b'{"type": 5}', "unknown_type"),
    ],
)
def test_framing_rejected(data: bytes, expected: str) -> None:
    assert reason(data) == expected


def test_float_overflow_to_infinity() -> None:
    """json.loads turns 1e999 into inf without calling parse_constant."""
    data = encode(BASE_POS).replace(b'"lat": 47.5', b'"lat": 1e999')
    assert reason(data) == "field_lat"


def test_huge_integer() -> None:
    """float(10**400) raises OverflowError, which must not escape."""
    data = encode(BASE_POS).replace(b'"lat": 47.5', b'"lat": 1' + b"0" * 400)
    assert reason(data) == "field_lat"


def test_too_many_keys() -> None:
    obj = {**BASE_MSG, **{f"k{i}": i for i in range(40)}}
    assert reason(encode(obj)) == "json_too_many_keys"


def test_unknown_scalar_keys_are_ignored() -> None:
    packet = parse_datagram(msg(future_field="x"))
    assert isinstance(packet, TextMessagePacket)


# --- field validation -------------------------------------------------------


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"src_type": "evil"}, "field_src_type"),
        ({"src": 5}, "field_src"),
        ({"src": ""}, "path_length"),
        ({"src": "TST1-12," * 20}, "path_length"),
        ({"src": "tst1-12"}, "path_callsign"),
        # Cyrillic "\u041e" instead of Latin "O"
        ({"src": "D\u041e8RE-12"}, "path_callsign"),
        ({"src": "TST1-12,<script>"}, "path_callsign"),
        ({"src": "TST1-123"}, "path_callsign"),
        ({"msg_id": "XYZ"}, "field_msg_id"),
        ({"msg_id": 1234}, "field_msg_id"),
        ({"dst": "<b>"}, "field_dst"),
        ({"dst": "123456"}, "field_dst"),
        ({"dst": "TOOLONGCALL"}, "field_dst"),
        ({"msg": 5}, "field_msg"),
        ({"msg": "x" * 257}, "field_msg"),
        ({"firmware": "5.x"}, "field_firmware"),
        ({"firmware": True}, "field_firmware"),
        ({"firmware": 999}, "field_firmware"),
        ({"fw_sub": "\n"}, "field_fw_sub"),
        ({"fw_sub": "ab"}, "field_fw_sub"),
        ({"rssi": True}, "field_rssi"),
        ({"rssi": -500}, "field_rssi"),
        ({"rssi": 1.5}, "field_rssi"),
        ({"snr": 99}, "field_snr"),
        ({"snr": "5"}, "field_snr"),
        ({"hw_id": -1}, "field_hw_id"),
    ],
)
def test_message_fields_rejected(changes: dict[str, Any], expected: str) -> None:
    assert reason(msg(**changes)) == expected


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"lat": 91}, "field_lat"),
        ({"lat": -1}, "field_lat"),
        ({"lat_dir": "X"}, "field_lat"),
        ({"long": 181}, "field_long"),
        ({"long_dir": 1}, "field_long"),
        ({"alt": 1.5}, "field_alt"),
        ({"alt": 10**9}, "field_alt"),
        ({"batt": 101}, "field_batt"),
        ({"aprs_symbol": "ab"}, "field_aprs_symbol"),
        ({"aprs_symbol": "\u00e4"}, "field_aprs_symbol"),
        ({"aprs_symbol_group": "\n"}, "field_aprs_symbol_group"),
    ],
)
def test_position_fields_rejected(changes: dict[str, Any], expected: str) -> None:
    assert reason(pos(**changes)) == expected


def test_position_southern_western_hemisphere() -> None:
    packet = parse_datagram(pos(lat_dir="S", long_dir="W"))
    assert packet.latitude == -47.5  # type: ignore[union-attr]
    assert packet.longitude == -11.5  # type: ignore[union-attr]


def test_position_without_fix() -> None:
    packet = parse_datagram(pos(lat=0, long=0, alt=0, aprs_symbol=""))
    assert packet.latitude is None  # type: ignore[union-attr]
    assert packet.altitude_m is None  # type: ignore[union-attr]
    assert packet.symbol is None  # type: ignore[union-attr]


def test_telemetry_implausible_values_are_dropped() -> None:
    data = encode(
        {
            "src_type": "lora",
            "type": "tele",
            "src": "TST1-12",
            "temp1": 500,
            "hum": 50,
            "din": "0101",
        }
    )
    packet = parse_datagram(data)
    assert packet.temperature_1 is None  # type: ignore[union-attr]
    assert packet.humidity == 50  # type: ignore[union-attr]
    assert packet.digital_inputs == "0101"  # type: ignore[union-attr]


def test_telemetry_bad_digital_inputs() -> None:
    data = encode({"src_type": "lora", "type": "tele", "src": "TST1-12", "din": "x"})
    assert reason(data) == "field_din"


# --- untrusted text -----------------------------------------------------------


def test_html_is_kept_as_text() -> None:
    """Escaping is the render layer's job; the parser must not alter or drop it."""
    payload = '<img src=x onerror="alert(1)">'
    packet = parse_datagram(msg(msg=payload))
    assert isinstance(packet, TextMessagePacket)
    assert packet.text == payload
    assert not packet.text_cleaned


@pytest.mark.parametrize(
    "dirty",
    [
        "line1\nFAKE LOG LINE",
        "abc\r\n",
        "admin\u202egnp.exe",
        "zero\u200bwidth",
        "bell\x07",
        "nul\x00byte",
    ],
)
def test_control_and_format_characters_removed(dirty: str) -> None:
    packet = parse_datagram(msg(msg=dirty))
    assert isinstance(packet, TextMessagePacket)
    assert packet.text_cleaned
    assert all(ch.isprintable() for ch in packet.text)


def test_umlauts_are_kept() -> None:
    text = "Gr\u00fc\u00dfe aus Bayern, sch\u00f6n \u00fcber 10 Grad"
    packet = parse_datagram(msg(dst="26298", msg=text))
    assert isinstance(packet, TextMessagePacket)
    assert packet.text == text
    assert not packet.text_cleaned


def test_sequence_only_for_direct_messages() -> None:
    packet = parse_datagram(msg(dst="*", msg="Hallo{123"))
    assert isinstance(packet, TextMessagePacket)
    assert packet.text == "Hallo{123"
    assert packet.sequence is None


def test_sequence_with_closing_brace() -> None:
    packet = parse_datagram(msg(dst="OWN1-12", msg="Hallo{12}"))
    assert isinstance(packet, TextMessagePacket)
    assert (packet.text, packet.sequence) == ("Hallo", 12)


def test_group_message() -> None:
    packet = parse_datagram(msg(dst="262", msg="Gruppe"))
    assert isinstance(packet, TextMessagePacket)
    assert packet.destination_kind.value == "group"


def test_ack_text_for_other_station_is_a_normal_message() -> None:
    """An ack text addressed to someone else must not acknowledge our message."""
    packet = parse_datagram(msg(dst="OWN1-12", msg="OTHER1-1 :ack724"))
    assert isinstance(packet, TextMessagePacket)


def test_ack_text_in_broadcast_is_a_normal_message() -> None:
    packet = parse_datagram(msg(dst="*", msg="OWN1-12  :ack724"))
    assert isinstance(packet, TextMessagePacket)


def test_reject_text() -> None:
    packet = parse_datagram(msg(dst="OWN1-12", msg="OWN1-12  :rej5"))
    assert isinstance(packet, AckMessagePacket)
    assert packet.rejected


# --- delivery status datagram ---------------------------------------------


def test_delivery_status() -> None:
    data = encode(
        {"type": "ack", "msg_id": "40000ED4", "status": 2, "from": "OWN1-9", "via": "udp"}
    )
    packet = parse_datagram(data)
    assert isinstance(packet, DeliveryStatusPacket)
    assert packet.status is DeliveryStatus.DELIVERED
    assert packet.msg_id.counter == 0x2D4


def test_delivery_status_minimal() -> None:
    packet = parse_datagram(encode({"type": "ack", "msg_id": "40000ED4", "status": 0}))
    assert isinstance(packet, DeliveryStatusPacket)
    assert packet.from_station is None
    assert packet.via is None


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"status": 9}, "field_status"),
        ({"from": "<x>"}, "field_from"),
        ({"via": 'u"dp'}, "field_via"),
    ],
)
def test_delivery_status_rejected(changes: dict[str, Any], expected: str) -> None:
    data = encode({"type": "ack", "msg_id": "40000ED4", "status": 1, **changes})
    assert reason(data) == expected


# --- fuzzing -----------------------------------------------------------------


@given(st.binary(max_size=1200))
@settings(max_examples=500)
def test_fuzz_bytes_never_crash(data: bytes) -> None:
    with contextlib.suppress(InvalidPacketError):
        parse_datagram(data)


_scalars = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-(10**6), max_value=10**6),
    st.floats(allow_nan=False, allow_infinity=False),
    st.text(max_size=40),
)


@given(st.dictionaries(st.sampled_from(sorted(BASE_MSG) + sorted(BASE_POS)), _scalars, max_size=5))
@settings(max_examples=500, suppress_health_check=[HealthCheck.too_slow])
def test_fuzz_mutated_packets_never_crash(changes: dict[str, Any]) -> None:
    for base in (BASE_MSG, BASE_POS):
        data = encode({**base, **changes})
        with contextlib.suppress(InvalidPacketError):
            parse_datagram(data)
