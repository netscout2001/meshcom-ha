"""Remote management frames ("RM1").

The vectors marked "firmware" were produced by compiling the firmware's
own ``src/remote_cmd.cpp`` (main 70ae124d) natively: it accepted the
commands built here (verdict ``ok``/``sync``) and signed the replies.
"""

from __future__ import annotations

import pytest

from aiomeshcom import InvalidOutgoingError
from aiomeshcom.builder import build_rm_message, build_text_message, validate_rm_message
from aiomeshcom.kiss import build_kiss_message
from aiomeshcom.rm import (
    build_command,
    derive_key,
    is_command_frame,
    parse_status,
    parse_sync,
    validate_command,
    verify_reply,
)

TARGET = "DL1ABC-1"
COMMANDER = "DO0XYZ-12"
KEY = derive_key("Secret12  ")
STATUS = "ok v=4.40a up=12 bat=88 heap=90 s=GtDMw p=22/0/30 rs=1"


@pytest.mark.parametrize(
    ("counter", "cmd", "args", "expected"),
    [
        (6, "status", "", "RM1 6 status 5c3dfef3b6d97ae8"),
        (6, "txpower", "22", "RM1 6 txpower 22 e57609ccfc3aeec3"),
        (6, "gps", "off", "RM1 6 gps off 601f8105e010483b"),
        (6, "led", "flash", "RM1 6 led flash 782ab6176306bcca"),
        (0, "sync", "", "RM1 0 sync 0c5b11100445a29b"),
    ],
)
def test_command_matches_firmware(counter: int, cmd: str, args: str, expected: str) -> None:
    text = build_command(
        KEY, target=TARGET, commander=COMMANDER, counter=counter, cmd=cmd, args=args
    )
    assert text == expected
    assert is_command_frame(text)


def test_reply_signed_by_firmware() -> None:
    reply = f"RM1 6 {STATUS} 815fa4e02175417f"
    assert verify_reply(KEY, reply, target=TARGET, commander=COMMANDER, counter=6) == STATUS
    # Sequence suffix of a DM is ignored.
    assert verify_reply(KEY, reply + "{12", target=TARGET, commander=COMMANDER, counter=6) == STATUS
    sync = f"RM1 0 {STATUS} 2c9bcfdfeb64f4c1"
    assert verify_reply(KEY, sync, target=TARGET, commander=COMMANDER, counter=0) == STATUS


@pytest.mark.parametrize(
    "change",
    [
        {"counter": 7},
        {"target": "DL1ABC-2"},
        {"commander": "DO0XYZ-11"},
        {"key": derive_key("other")},
    ],
)
def test_reply_rejected_when_anything_differs(change: dict[str, object]) -> None:
    args: dict[str, object] = {
        "key": KEY,
        "target": TARGET,
        "commander": COMMANDER,
        "counter": 6,
    }
    args.update(change)
    reply = f"RM1 6 {STATUS} 815fa4e02175417f"
    assert (
        verify_reply(
            args["key"],  # type: ignore[arg-type]
            reply,
            target=str(args["target"]),
            commander=str(args["commander"]),
            counter=int(args["counter"]),  # type: ignore[call-overload]
        )
        is None
    )


@pytest.mark.parametrize(
    "text",
    [
        "RM1 6 ok rebooting 815FA4E02175417F",
        "RM1 06 ok x 815fa4e02175417f",
        "RM1 6 maybe x 815fa4e02175417f",
        "RM1 6 ok <b> 815fa4e02175417f",
        "RM1 6 ok " + "x" * 120 + " 815fa4e02175417f",
        "hello",
    ],
)
def test_reply_malformed(text: str) -> None:
    assert verify_reply(KEY, text, target=TARGET, commander=COMMANDER, counter=6) is None


def test_reply_tampered_result() -> None:
    reply = f"RM1 6 {STATUS.replace('bat=88', 'bat=99')} 815fa4e02175417f"
    assert verify_reply(KEY, reply, target=TARGET, commander=COMMANDER, counter=6) is None


@pytest.mark.parametrize("password", ["", "   ", "x" * 15, "pässwort", "tab\tx"])
def test_bad_passwords(password: str) -> None:
    with pytest.raises(InvalidOutgoingError):
        derive_key(password)


def test_trailing_spaces_ignored() -> None:
    assert derive_key("abc   ") == derive_key("abc")


@pytest.mark.parametrize(
    ("cmd", "args"),
    [
        ("status", "x"),
        ("gps", "maybe"),
        ("gps", ""),
        ("led", "blink"),
        ("txpower", "-1"),
        ("txpower", "022"),
        ("txpower", "1000"),
        ("txpower", "²"),
        ("name", "x"),
        ("upd", "go v1"),
        ("reboot", "now"),
    ],
)
def test_command_validation(cmd: str, args: str) -> None:
    with pytest.raises(InvalidOutgoingError):
        validate_command(cmd, args)


def test_build_command_checks() -> None:
    with pytest.raises(InvalidOutgoingError):
        build_command(b"short", target=TARGET, commander=COMMANDER, counter=1, cmd="status")
    with pytest.raises(InvalidOutgoingError):
        build_command(KEY, target="bad call", commander=COMMANDER, counter=1, cmd="status")
    with pytest.raises(InvalidOutgoingError):
        build_command(KEY, target=TARGET, commander=COMMANDER, counter=0, cmd="status")
    with pytest.raises(InvalidOutgoingError):
        build_command(KEY, target=TARGET, commander=COMMANDER, counter=2**32, cmd="status")
    with pytest.raises(InvalidOutgoingError):
        build_command(KEY, target=TARGET, commander=COMMANDER, counter=5, cmd="sync")


@pytest.mark.parametrize(
    "text",
    [
        "RM1 6 status",
        "RM1 6 status 5c3dfef3b6d97ae",
        "RM2 6 status 5c3dfef3b6d97ae8",
        "RM1 06 status 5c3dfef3b6d97ae8",
        "RM1 x status 5c3dfef3b6d97ae8",
        "RM1 6 name joe 5c3dfef3b6d97ae8",
        "RM1 0 status 5c3dfef3b6d97ae8",
        "RM1 6 sync 5c3dfef3b6d97ae8",
        "RM1 99999999999 status 5c3dfef3b6d97ae8",
        "RM1 6 gps on off 5c3dfef3b6d97ae8",
    ],
)
def test_not_a_command_frame(text: str) -> None:
    assert not is_command_frame(text)


def test_status_parsing() -> None:
    status = parse_status(STATUS)
    assert status is not None
    assert status.version == "4.40a"
    assert status.uptime_minutes == 12
    assert status.battery == 88
    assert status.heap_kb == 90
    assert status.switches == {
        "gps": True,
        "track": False,
        "display": True,
        "mesh": True,
        "gateway": False,
    }
    assert not status.led_supported
    assert (status.tx_power, status.tx_power_min, status.tx_power_max) == (22, 0, 30)
    assert status.strict is True

    led = parse_status("ok v=4.40a up=1 bat=0 heap=1 s=gtdmwL p=x rs=7 extra=1")
    assert led is not None
    assert led.led_supported
    assert led.switches["led"] is True
    assert led.tx_power is None
    assert led.strict is None

    odd = parse_status("ok v=<x> up=-1 bat=101 heap=x s=GTDMW p=1/2")
    assert odd is not None
    assert odd.version is None
    assert odd.uptime_minutes is None
    assert odd.battery is None
    assert odd.tx_power is None


@pytest.mark.parametrize(
    "result",
    ["ok rebooting", "ok v=1 s=GTD", "ok v=1 s=XTDMW", "ok v=1", "err blocked"],
)
def test_not_a_status(result: str) -> None:
    assert parse_status(result) is None


def test_sync_parsing() -> None:
    assert parse_sync("ok ctr=41 v=4.40a") == 41
    assert parse_sync("ok ctr=0") == 0
    assert parse_sync("ok ctr=041 v=1") is None
    assert parse_sync("ok ctr=99999999999") is None
    assert parse_sync("ok sent") is None


def test_transport_builders() -> None:
    frame = "RM1 6 status 5c3dfef3b6d97ae8"
    assert b'"msg":"RM1 6 status 5c3dfef3b6d97ae8"' in build_rm_message(TARGET, frame)
    with pytest.raises(InvalidOutgoingError):
        build_rm_message("*", frame)
    with pytest.raises(InvalidOutgoingError):
        validate_rm_message(TARGET, "RM1 6 name x 5c3dfef3b6d97ae8")
    # The free-text paths still refuse the prefix.
    with pytest.raises(InvalidOutgoingError):
        build_text_message(TARGET, frame)
    with pytest.raises(InvalidOutgoingError):
        build_kiss_message(COMMANDER, TARGET, frame)
    assert frame.encode() in build_kiss_message(COMMANDER, TARGET, frame, control=True)
    with pytest.raises(InvalidOutgoingError):
        build_kiss_message(COMMANDER, TARGET, frame, 5, control=True)
