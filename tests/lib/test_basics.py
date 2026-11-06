"""Tests for callsigns, text cleaning and models."""

from __future__ import annotations

import pytest

from aiomeshcom import Firmware, InvalidPacketError, MessageId, is_callsign, is_destination
from aiomeshcom.text import clean_text, contains_unwanted


@pytest.mark.parametrize(
    "value", ["DO8RE-12", "DO8RE-9", "HB9AAA-4", "OE1AAA-63", "DB0AAA-12", "DK1AA-98", "DL1AA"]
)
def test_valid_callsigns(value: str) -> None:
    assert is_callsign(value)


@pytest.mark.parametrize(
    "value",
    ["do8re-12", "DO8RE-123", "DO8RE-", "AB", "ABCDEFGH", "12345", "ABCDE", "D\u041e8RE-12", ""],
)
def test_invalid_callsigns(value: str) -> None:
    assert not is_callsign(value)


@pytest.mark.parametrize(
    ("value", "valid"),
    [("*", True), ("262", True), ("99999", True), ("123456", False), ("**", False)],
)
def test_destinations(value: str, valid: bool) -> None:
    assert is_destination(value) is valid


def test_clean_text() -> None:
    assert clean_text("plain") == ("plain", False)
    assert clean_text("a\u200bb\nc") == ("abc", True)
    assert contains_unwanted("\ufeff")
    assert not contains_unwanted("Gr\u00fc\u00dfe 73")


def test_message_id() -> None:
    msg_id = MessageId(0x63CF32D4)
    assert msg_id.counter == 724
    assert msg_id.node_id == 0x63CF32D4 >> 10
    assert str(msg_id) == "63CF32D4"


def test_firmware_str() -> None:
    assert str(Firmware(minor=40, sub="a")) == "4.40a"
    assert str(Firmware(minor=5, sub=None)) == "4.05"
    assert str(Firmware(minor=None, sub=None)) == "unknown"


def test_error_reason_does_not_echo_input() -> None:
    err = InvalidPacketError("field_msg")
    assert str(err) == "invalid packet: field_msg"
