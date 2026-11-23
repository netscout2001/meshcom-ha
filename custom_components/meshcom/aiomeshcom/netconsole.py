"""Client for the node's net console (TCP port 2323, ESP32 only).

Firmware ``src/net_console.cpp``: plain TCP, one client. With a node
password the node sends ``NONCE: <32 hex>``, the client answers with
HMAC-SHA256(password, nonce) as 64 hex characters, and the node replies
``OK`` (followed by a banner) or ``FAIL``. Without a password the node sends
``OK`` right away. Afterwards the console mirrors the node's whole serial
output and accepts command lines.

A new successful login replaces the running session, so a console session
is meant to be short and opened on demand.
"""

from __future__ import annotations

import asyncio
import contextlib
import itertools
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Final

from .errors import InvalidOutgoingError, MeshComError
from .kiss import auth_response, parse_nonce
from .kiss_client import set_keepalive

NET_CONSOLE_PORT: Final = 2323
CONNECT_TIMEOUT: Final = 10.0
HANDSHAKE_TIMEOUT: Final = 15.0
MAX_LINE_CHARS: Final = 400
MAX_COMMAND_CHARS: Final = 120
_READ_LIMIT: Final = 4096

_COMMAND_RE: Final = re.compile(r"--[A-Za-z0-9][\x20-\x7e]*")

# Command words by risk (checked against the firmware's console commands, 4.40a.11.22).
UNREACHABLE: Final = "unreachable"
CREDENTIALS: Final = "credentials"
IDENTITY: Final = "identity"
RADIO: Final = "radio"
HARDWARE: Final = "hardware"
SECURITY: Final = "security"
SYSTEM: Final = "system"
_RISK: Final = {
    "setssid": UNREACHABLE,
    "setpwd": UNREACHABLE,
    "deepsleep": UNREACHABLE,
    "ota-update": UNREACHABLE,
    "update": UNREACHABLE,
    "autoupdate": UNREACHABLE,
    # Cut the connection of Home Assistant (UDP, KISS, console, address).
    "wifiap on": UNREACHABLE,
    "wifi off": UNREACHABLE,
    "wifitxpower": UNREACHABLE,
    "netmode": UNREACHABLE,
    "setownip": UNREACHABLE,
    "setowngw": UNREACHABLE,
    "setownms": UNREACHABLE,
    "setowndns": UNREACHABLE,
    "extudp off": UNREACHABLE,
    "extudpip": UNREACHABLE,
    "kiss off": UNREACHABLE,
    "netconsole off": UNREACHABLE,
    "passwd": CREDENTIALS,
    "webpwd": CREDENTIALS,
    "btcode": CREDENTIALS,
    "aprsis pass": CREDENTIALS,
    # Who and where the node says it is on air and on APRS-IS.
    "setcall": IDENTITY,
    "setctry": IDENTITY,
    "setudpcall": IDENTITY,
    "aprswxcall": IDENTITY,
    "setname": IDENTITY,
    "setlat": IDENTITY,
    "setlon": IDENTITY,
    "setalt": IDENTITY,
    # LoRa settings: wrong values leave the mesh.
    "txpower": RADIO,
    "txfreq": RADIO,
    "txbw": RADIO,
    "txsf": RADIO,
    "txcr": RADIO,
    "setboostedgain": RADIO,
    # Pins and what is wired to them (relays, sensors, buttons).
    "gpio": HARDWARE,
    "gpiocontrol": HARDWARE,
    "setout": HARDWARE,
    "setio": HARDWARE,
    "relay on": HARDWARE,
    "relay off": HARDWARE,
    "button gpio": HARDWARE,
    "onewire gpio": HARDWARE,
    "analog gpio": HARDWARE,
    "softser rxpin": HARDWARE,
    "softser txpin": HARDWARE,
    "windpin": HARDWARE,
    # Who may control the node.
    "kiss auth off": SECURITY,
    "remotemgmt": SECURITY,
    "rmstrictsecurity": SECURITY,
    # Erase settings or files, or start the bootloader.
    "cleanflash": SYSTEM,
    "spiffs reset": SYSTEM,
    "flashpoke": SYSTEM,
    "dfu": SYSTEM,
}


class ConsoleError(MeshComError):
    """Base class of net console errors."""


class ConsoleRefusedError(ConsoleError):
    """The node refused the connection: the net console is off."""


class ConsoleUnreachableError(ConsoleError):
    """No answer from the node (timeout, no route)."""


class ConsoleAuthError(ConsoleError):
    """The node rejected the password (``FAIL``)."""


class ConsoleAuthRequiredError(ConsoleError):
    """The node asks for a password, but none is configured."""


class ConsoleProtocolError(ConsoleError):
    """The node answered something that is not the console handshake."""


_SEVERITY: Final = (UNREACHABLE, SYSTEM, CREDENTIALS, SECURITY, RADIO, IDENTITY, HARDWARE)


def _segments(line: str) -> list[str]:
    """The commands the firmware runs for one console line.

    The net console hands a line to ``commandAction()``, which starts a new
    command at every ``--`` after the first two characters, also inside a
    word or an argument (``--info --setssid x`` runs both).
    """
    cuts = [0, *(i for i in range(2, len(line)) if line.startswith("--", i)), len(line)]
    return [line[a:b].strip() for a, b in itertools.pairwise(cuts)]


def command_risk(command: str) -> str | None:
    """Most severe risk class of the commands in one line, or None."""
    found = set()
    for segment in _segments(command.strip()):
        if not segment.startswith("--"):
            continue
        # A name is one to three words: "setssid", "kiss off", "kiss auth off".
        words = segment[2:].lower().split()
        for name in (" ".join(words[:3]), " ".join(words[:2]), " ".join(words[:1])):
            if (risk := _RISK.get(name)) is not None:
                found.add(risk)
                break
    return next((risk for risk in _SEVERITY if risk in found), None)


def validate_command(command: str) -> str:
    """The command line to send; raises for anything that is not one line."""
    command = command.strip()
    if len(command) > MAX_COMMAND_CHARS or not _COMMAND_RE.fullmatch(command):
        raise InvalidOutgoingError("console_command")
    return command


# The radio line of "--info" (firmware 4.40a): "...FREQ 433.1750 MHz TXPWR 22
# dBm RXBOOST off"; older firmware has no RXBOOST. The country line comes
# just before it: "...CTRY EU8". Nothing else of "--info" is read (it also
# shows the node password, the BT PIN, the WLAN name and IP addresses).
_FREQ_RE: Final = re.compile(
    r"^\.\.\.FREQ (\d{3,4}\.\d{1,6}) MHz TXPWR (-?\d{1,2}) dBm(?: RXBOOST (on|off))?\s*$"
)
_CTRY_RE: Final = re.compile(r"^\.\.\.CTRY ([A-Za-z0-9]{1,8})\s*$")
_FREQ_RANGE: Final = (137.0, 1100.0)
_POWER_RANGE: Final = (-10, 40)


@dataclass(frozen=True, slots=True)
class RadioInfo:
    """Radio settings from the node's "--info" output."""

    frequency_mhz: float
    tx_power_dbm: int
    #: None on firmware that does not report it.
    rx_boost: bool | None
    country: str | None


def parse_radio_info(lines: Iterable[str]) -> RadioInfo | None:
    """Radio settings from console lines, or None if they are not there or implausible."""
    country: str | None = None
    info: RadioInfo | None = None
    for line in lines:
        if (match := _CTRY_RE.match(line)) is not None:
            country = match.group(1)
            continue
        if (match := _FREQ_RE.match(line)) is None:
            continue
        frequency, power = float(match.group(1)), int(match.group(2))
        if not (
            _FREQ_RANGE[0] <= frequency <= _FREQ_RANGE[1]
            and _POWER_RANGE[0] <= power <= _POWER_RANGE[1]
        ):
            continue
        boost = None if match.group(3) is None else match.group(3) == "on"
        info = RadioInfo(frequency, power, boost, country)
    return info


def clean_line(raw: bytes) -> str:
    """One output line as safe plain text: bounded, without control characters."""
    text = raw.decode("utf-8", errors="replace").rstrip("\r\n")
    text = "".join(char if char.isprintable() or char == "\t" else "�" for char in text)
    return text[:MAX_LINE_CHARS]


class NetConsole:
    """One console session."""

    def __init__(
        self,
        host: str,
        password: str | None,
        on_line: Callable[[str], None],
        *,
        port: int = NET_CONSOLE_PORT,
    ) -> None:
        self.host = host
        self.port = port
        self._password = password
        self._on_line = on_line
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self.open_access = False
        """True when the node granted access without a password."""

    @property
    def connected(self) -> bool:
        """True while the session is up."""
        return self._writer is not None and not self._writer.is_closing()

    async def connect(self) -> None:
        """Open the connection and log in; raises a :class:`ConsoleError`."""
        try:
            async with asyncio.timeout(CONNECT_TIMEOUT):
                reader, writer = await asyncio.open_connection(
                    self.host, self.port, limit=_READ_LIMIT
                )
        except ConnectionRefusedError as err:
            raise ConsoleRefusedError("refused") from err
        except (TimeoutError, OSError) as err:
            raise ConsoleUnreachableError(type(err).__name__) from err
        sock = writer.get_extra_info("socket")
        if sock is not None:
            set_keepalive(sock)
        try:
            async with asyncio.timeout(HANDSHAKE_TIMEOUT):
                await self._handshake(reader, writer)
        except ConsoleError:
            writer.close()
            raise
        except (TimeoutError, OSError, asyncio.IncompleteReadError, ValueError) as err:
            writer.close()
            raise ConsoleProtocolError(type(err).__name__) from err
        self._reader = reader
        self._writer = writer

    async def _handshake(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        first = await reader.readline()
        if first.strip() == b"OK":
            self.open_access = True
            return
        nonce = parse_nonce(first)
        if nonce is None:
            raise ConsoleProtocolError("challenge")
        if not self._password:
            raise ConsoleAuthRequiredError("password")
        try:
            writer.write(auth_response(self._password, nonce))
        except InvalidOutgoingError as err:
            raise ConsoleAuthError("password") from err
        await writer.drain()
        answer = (await reader.readline()).strip()
        if answer == b"FAIL" or not answer:
            raise ConsoleAuthError("rejected")
        if answer != b"OK":
            raise ConsoleProtocolError("answer")

    async def run(self) -> None:
        """Deliver output lines until the node closes the session."""
        reader = self._reader
        if reader is None:
            raise ConsoleError("not connected")
        try:
            while True:
                try:
                    raw = await reader.readuntil(b"\n")
                except asyncio.LimitOverrunError as err:
                    # An endless line: deliver what fits and drop the rest.
                    raw = await reader.readexactly(err.consumed)
                except asyncio.IncompleteReadError as err:
                    if err.partial:
                        self._on_line(clean_line(err.partial))
                    return
                self._on_line(clean_line(raw))
        except OSError:
            return
        finally:
            await self.close()

    async def send(self, command: str) -> None:
        """Send one validated command line."""
        line = validate_command(command)
        if self._writer is None or self._writer.is_closing():
            raise ConsoleError("not connected")
        self._writer.write(line.encode("ascii") + b"\n")
        await self._writer.drain()

    async def close(self) -> None:
        """Close the session (idempotent)."""
        writer, self._writer, self._reader = self._writer, None, None
        if writer is not None:
            writer.close()
            with contextlib.suppress(OSError, asyncio.CancelledError):
                await writer.wait_closed()
