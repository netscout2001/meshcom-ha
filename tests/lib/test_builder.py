"""Tests for outgoing datagrams."""

from __future__ import annotations

import json

import pytest

from aiomeshcom import (
    InvalidOutgoingError,
    TextMessagePacket,
    build_external_telemetry,
    build_text_message,
    parse_datagram,
)


@pytest.mark.parametrize("destination", ["*", "262", "OWN1-9"])
def test_text_message(destination: str) -> None:
    data = build_text_message(destination, "Hallo Welt")
    assert json.loads(data) == {"type": "msg", "dst": destination, "msg": "Hallo Welt"}


def test_umlauts_count_as_two_bytes() -> None:
    build_text_message("*", "\u00e4" * 75)
    with pytest.raises(InvalidOutgoingError) as err:
        build_text_message("*", "\u00e4" * 76)
    assert err.value.reason == "text_too_long"


@pytest.mark.parametrize(
    ("destination", "text", "expected"),
    [
        ("<x>", "hi", "destination"),
        ("TOOLONGCALL1", "hi", "destination"),
        ("own1-9", "hi", "destination"),
        ("*", "", "text_empty"),
        ("*", "   ", "text_empty"),
        ("*", "x" * 151, "text_too_long"),
        ("*", "line\nbreak", "text_control_characters"),
        ("*", "rl\u202eo", "text_control_characters"),
        ("*", "{CET}2026-01-01 00:00:00", "text_reserved_prefix"),
        ("OWN1-9", "RM1 1 reboot " + "0" * 16, "text_reserved_prefix"),
        ("TEST", "hi", "destination"),
        ("OWN1-9", "OWN1-12  :ack724", "text_reserved_suffix"),
        ("OWN1-9", "fake :REJ1", "text_reserved_suffix"),
        ("OWN1-9", "Hallo{123", "text_reserved_suffix"),
        ("OWN1-9", "Hallo{12}", "text_reserved_suffix"),
    ],
)
def test_text_message_rejected(destination: str, text: str, expected: str) -> None:
    with pytest.raises(InvalidOutgoingError) as err:
        build_text_message(destination, text)
    assert err.value.reason == expected


def test_escaping_can_exceed_node_buffer() -> None:
    """150 quote characters become 300 bytes of JSON; the node reads only 254."""
    with pytest.raises(InvalidOutgoingError) as err:
        build_text_message("*", '"' * 150)
    assert err.value.reason == "datagram_too_long"


def test_quotes_are_escaped() -> None:
    data = build_text_message("*", 'say "hi" \\ bye')
    assert json.loads(data)["msg"] == 'say "hi" \\ bye'


def test_round_trip_through_parser() -> None:
    sent = json.loads(build_text_message("OWN1-9", "Test"))
    echo = {
        "src_type": "node",
        "type": "msg",
        "src": "OWN1-12",
        "msg_id": "40000ED4",
        "firmware": "4.40",
        "fw_sub": "a",
        "rssi": 0,
        "snr": 0,
        "dst": sent["dst"],
        "msg": sent["msg"] + "{724",
    }
    packet = parse_datagram(json.dumps(echo).encode())
    assert isinstance(packet, TextMessagePacket)
    assert (packet.text, packet.sequence) == ("Test", 724)


def test_external_telemetry() -> None:
    data = build_external_telemetry({"temp": 23.333, "hum": 60, "press": 1018.5})
    assert json.loads(data) == {"type": "tele", "temp": 23.33, "hum": 60.0, "press": 1018.5}


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        ({}, "telemetry_empty"),
        ({"evil": 1.0}, "telemetry_field"),
        ({"temp": True}, "telemetry_value"),
        ({"temp": "20"}, "telemetry_value"),
        ({"temp": float("nan")}, "telemetry_range"),
        ({"hum": 101.0}, "telemetry_range"),
    ],
)
def test_external_telemetry_rejected(values: dict[str, float], expected: str) -> None:
    with pytest.raises(InvalidOutgoingError) as err:
        build_external_telemetry(values)
    assert err.value.reason == expected
