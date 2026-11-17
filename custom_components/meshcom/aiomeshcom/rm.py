"""Authenticated remote management between nodes ("RM1").

The firmware (``src/remote_cmd.h``, issue icssw-org/MeshCom-Firmware#1189)
accepts a direct message ``RM1 <ctr> <cmd>[ <args>] <tag>`` from any
station that knows the target node's password:

* ``K`` = SHA-256 of the target's ``--passwd`` (trailing spaces stripped),
* ``tag`` = first 8 bytes (16 lower-case hex) of HMAC-SHA256(K, canonical),
* canonical = ``RM1|<target>|<commander>|<ctr>|<cmd>[ <args>]``.

The target answers ``RM1 <ctr> ok <status> <rtag>`` or
``RM1 <ctr> err <reason> <rtag>`` with ``rtag`` over
``RM1R|<target>|<commander>|<ctr>|<result>``. Wrong tags, replays, rate and
lockout rejects are silent: no answer at all.

This module only builds and verifies frames. It never sends anything and
keeps no state; the counter is the caller's.
"""

from __future__ import annotations

import hashlib
import hmac
import re
from dataclasses import dataclass
from typing import Final

from .callsign import is_callsign
from .errors import InvalidOutgoingError

MAX_PASSWORD: Final = 14
"""The firmware's ``--passwd`` holds at most 14 characters."""

MAX_COUNTER: Final = 4_294_967_295
MAX_RESULT: Final = 108
"""Longest result text a reply can carry (``RM_MAX_RESULT``)."""

RATE_INTERVAL_SECONDS: Final = 10
"""Minimum spacing of accepted commands with strict security (``RM_RATE_MS``)."""

SYNC_INTERVAL_SECONDS: Final = 60
"""Minimum spacing of accepted syncs with strict security (``RM_SYNC_RATE_MS``)."""

NO_ANSWER_SECONDS: Final = 180
"""The firmware declares "no answer" after 171 s (``RM_NOANSWER_MS``)."""

TOGGLES: Final = ("gps", "track", "display", "gateway", "mesh")
LED_MODES: Final = ("on", "off", "flash")
_ACTIONS: Final = ("status", "sendpos", "sendtrack", "reboot")

_TAG_RE: Final = re.compile(r"[0-9a-f]{16}")
_REPLY_RE: Final = re.compile(r"RM1 (0|[1-9][0-9]{0,9}) ((?:ok|err)(?: [^ ]+)*) ([0-9a-f]{16})")
_SUFFIX_RE: Final = re.compile(r"\{[0-9]{1,3}\}?\Z")
_RESULT_CHARS: Final = re.compile(r"[A-Za-z0-9 \-./=+_@?(),*#]*")
_VERSION_RE: Final = re.compile(r"[0-9A-Za-z.]{1,16}")


def derive_key(password: str) -> bytes:
    """``K`` of a node password; raises for anything the firmware cannot hold."""
    stripped = password.rstrip(" ")
    if not stripped or len(stripped) > MAX_PASSWORD or not stripped.isascii():
        raise InvalidOutgoingError("password")
    if not stripped.isprintable():
        raise InvalidOutgoingError("password")
    return hashlib.sha256(stripped.encode("ascii")).digest()


def _tag(key: bytes, canonical: str) -> str:
    return hmac.new(key, canonical.encode("ascii"), hashlib.sha256).hexdigest()[:16]


def validate_command(cmd: str, args: str = "") -> None:
    """Raise unless ``cmd args`` is a command this library sends.

    A deliberately small subset of the firmware's allowlist: read-only
    status, the counter sync, the actions, the switches, TX power and the
    LED. Writing the name, beacon text, position, update or block list is
    left out.
    """
    if cmd == "sync" or cmd in _ACTIONS:
        if args:
            raise InvalidOutgoingError("rm_args")
        return
    if cmd in TOGGLES:
        if args not in ("on", "off"):
            raise InvalidOutgoingError("rm_args")
        return
    if cmd == "led":
        if args not in LED_MODES:
            raise InvalidOutgoingError("rm_args")
        return
    if cmd == "txpower":
        if not (args.isascii() and args.isdigit() and len(args) <= 3 and str(int(args)) == args):
            raise InvalidOutgoingError("rm_args")
        return
    raise InvalidOutgoingError("rm_command")


def build_command(  # noqa: PLR0913  # the protocol's six inputs, all keyword-only after key
    key: bytes, *, target: str, commander: str, counter: int, cmd: str, args: str = ""
) -> str:
    """The signed DM text for ``target``, sent by the node ``commander``."""
    if len(key) != hashlib.sha256().digest_size:
        raise InvalidOutgoingError("password")
    if not is_callsign(target) or not is_callsign(commander):
        raise InvalidOutgoingError("callsign")
    validate_command(cmd, args)
    if cmd == "sync":
        if counter != 0:
            raise InvalidOutgoingError("rm_counter")
    elif not 1 <= counter <= MAX_COUNTER:
        raise InvalidOutgoingError("rm_counter")
    body = f"{cmd} {args}" if args else cmd
    tag = _tag(key, f"RM1|{target}|{commander}|{counter}|{body}")
    return f"RM1 {counter} {body} {tag}"


def is_command_frame(text: str) -> bool:
    """True for a well-formed command text as :func:`build_command` makes it."""
    parts = text.split(" ")
    if len(parts) not in (4, 5) or parts[0] != "RM1" or not _TAG_RE.fullmatch(parts[-1]):
        return False
    counter = parts[1]
    if not counter.isdigit() or (counter != "0" and counter.startswith("0")):
        return False
    try:
        validate_command(parts[2], parts[3] if len(parts) == 5 else "")
    except InvalidOutgoingError:
        return False
    value = int(counter)
    return (value == 0) == (parts[2] == "sync") and value <= MAX_COUNTER


def verify_reply(key: bytes, text: str, *, target: str, commander: str, counter: int) -> str | None:
    """The result text of a genuine reply to ``counter``, else None.

    ``text`` is the DM as received (a trailing ``{nnn`` sequence is
    ignored). The reply must carry exactly the expected counter and a tag
    made with the target's key; anything else is treated as not received.
    """
    text = _SUFFIX_RE.sub("", text)
    match = _REPLY_RE.fullmatch(text)
    if match is None or int(match.group(1)) != counter:
        return None
    result = match.group(2)
    if len(result) > MAX_RESULT or not _RESULT_CHARS.fullmatch(result):
        return None
    want = _tag(key, f"RM1R|{target}|{commander}|{counter}|{result}")
    if not hmac.compare_digest(want, match.group(3)):
        return None
    return result


@dataclass(frozen=True, slots=True)
class RemoteStatus:
    """The answer to ``status``: ``ok v=.. up=.. bat=.. heap=.. s=.. p=c/min/max``."""

    version: str | None
    uptime_minutes: int | None
    battery: int | None
    heap_kb: int | None
    switches: dict[str, bool]
    led_supported: bool
    tx_power: int | None
    tx_power_min: int | None
    tx_power_max: int | None
    strict: bool | None


_SWITCH_LETTERS: Final = (
    ("G", "gps"),
    ("T", "track"),
    ("D", "display"),
    ("M", "mesh"),
    ("W", "gateway"),
    ("L", "led"),
)


def _small_int(value: str, low: int, high: int) -> int | None:
    if not re.fullmatch(r"-?[0-9]{1,10}", value):
        return None
    number = int(value)
    return number if low <= number <= high else None


def _parse_switches(value: str) -> tuple[dict[str, bool], bool] | None:
    if len(value) not in (5, 6):
        return None
    switches: dict[str, bool] = {}
    for char, (letter, name) in zip(value, _SWITCH_LETTERS, strict=False):
        if char == letter:
            switches[name] = True
        elif char == letter.lower():
            switches[name] = False
        else:
            return None
    return switches, len(value) == 6


def parse_status(result: str) -> RemoteStatus | None:
    """Fields of a status result; None if it is not one. Unknown tokens are ignored."""
    if not result.startswith("ok v="):
        return None
    fields: dict[str, str] = {}
    for token in result[3:].split(" "):
        name, sep, value = token.partition("=")
        if sep and name not in fields:
            fields[name] = value
    parsed = _parse_switches(fields.get("s", ""))
    if parsed is None:
        return None
    switches, led = parsed
    version = fields.get("v")
    power = fields.get("p", "").split("/")
    powers: list[int | None] = [None, None, None]
    if len(power) == 3:  # cur/min/max
        powers = [_small_int(part, -99, 99) for part in power]
    strict = fields.get("rs")
    return RemoteStatus(
        version=version if version is not None and _VERSION_RE.fullmatch(version) else None,
        uptime_minutes=_small_int(fields.get("up", ""), 0, 10**9),
        battery=_small_int(fields.get("bat", ""), 0, 100),
        heap_kb=_small_int(fields.get("heap", ""), 0, 10**6),
        switches=switches,
        led_supported=led,
        tx_power=powers[0],
        tx_power_min=powers[1],
        tx_power_max=powers[2],
        strict={"0": False, "1": True}.get(strict) if strict is not None else None,
    )


def parse_sync(result: str) -> int | None:
    """The target's counter high-water mark from ``ok ctr=<n> v=...``."""
    match = re.match(r"ok ctr=(0|[1-9][0-9]{0,9})(?: |\Z)", result)
    if match is None:
        return None
    value = int(match.group(1))
    return value if value <= MAX_COUNTER else None
