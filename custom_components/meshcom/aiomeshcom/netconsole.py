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
from collections.abc import Callable
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

# Command words by risk (checked against the firmware's console commands).
UNREACHABLE: Final = "unreachable"
CREDENTIALS: Final = "credentials"
IDENTITY: Final = "identity"
_RISK: Final = {
    "setssid": UNREACHABLE,
    "setpwd": UNREACHABLE,
    "deepsleep": UNREACHABLE,
    "ota-update": UNREACHABLE,
    "update": UNREACHABLE,
    "autoupdate": UNREACHABLE,
    "passwd": CREDENTIALS,
    "webpwd": CREDENTIALS,
    "setcall": IDENTITY,
    "setctry": IDENTITY,
    "txpower": IDENTITY,
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


_SEVERITY: Final = (UNREACHABLE, CREDENTIALS, IDENTITY)


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
        word = segment.split(" ", 1)[0]
        if word.startswith("--") and (risk := _RISK.get(word[2:].lower())) is not None:
            found.add(risk)
    return next((risk for risk in _SEVERITY if risk in found), None)


def validate_command(command: str) -> str:
    """The command line to send; raises for anything that is not one line."""
    command = command.strip()
    if len(command) > MAX_COMMAND_CHARS or not _COMMAND_RE.fullmatch(command):
        raise InvalidOutgoingError("console_command")
    return command


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
