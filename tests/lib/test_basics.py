"""Tests for callsigns, text cleaning and models."""

from __future__ import annotations

import pytest

from aiomeshcom import Firmware, InvalidPacketError, MessageId, is_callsign, is_destination
from aiomeshcom.text import clean_text, contains_unwanted


@pytest.mark.parametrize(
    "value", ["QX1YZ-12", "QX1YZ-9", "QH9AAA-4", "QE1AAA-63", "QB0AAA-12", "QK1AA-98", "QL1AA"]
)
def test_valid_callsigns(value: str) -> None:
    assert is_callsign(value)


@pytest.mark.parametrize(
    "value",
    ["qx1yz-12", "QX1YZ-123", "QX1YZ-", "AB", "ABCDEFGH", "12345", "ABCDE", "Q\u04251YZ-12", ""],
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


@pytest.mark.parametrize(
    "hidden",
    [
        "\U000e0041\U000e0042",  # tag characters (invisible ASCII copy)
        "\u00ad",  # SOFT HYPHEN
        "\u2028",  # LINE SEPARATOR
        "\u2029",  # PARAGRAPH SEPARATOR
        "\u3164",  # HANGUL FILLER
        "\u115f\u1160\uffa0",  # further Hangul fillers
        "\u2061",  # FUNCTION APPLICATION (format)
        "\ud800",  # lone surrogate
    ],
)
def test_clean_text_invisible(hidden: str) -> None:
    """Invisible characters are removed (security review F-8)."""
    assert clean_text(f"a{hidden}b") == ("ab", True)
    assert contains_unwanted(hidden)


def test_clean_text_keeps_visible() -> None:
    """Umlauts, emoji with variation selector and CJK stay untouched."""
    for text in ("\u00e4\u00f6\u00fc \u00df", "\u2764\ufe0f", "\u4f60\u597d", "73 de \U0001f4e1"):
        assert clean_text(text) == (text, False)


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
