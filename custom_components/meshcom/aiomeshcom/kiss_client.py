"""Asyncio connection to the KISS-over-TCP interface of a node.

One connection per node: the firmware serves a single client at a time.
:meth:`KissConnection.connect` opens the socket and answers the optional
authentication challenge, :meth:`KissConnection.run` reads until the
connection ends and passes decoded packets to the callback, and
:meth:`KissConnection.send_text` sends a message and waits for the node's
TX result.
"""

from __future__ import annotations

import asyncio
import contextlib
import secrets
import socket
from collections.abc import Callable
from typing import Final

from .errors import MeshComError
from .kiss import (
    KISS_TCP_PORT,
    KissDecoder,
    KissTxResult,
    TxStatus,
    auth_response,
    build_kiss_message,
    own_message_packet,
    parse_nonce,
)
from .models import Packet

#: How long the node may take to send its challenge after accepting.
CHALLENGE_TIMEOUT: Final = 3.0
#: The node waits 15 s for the answer; it answers OK/FAIL right away.
AUTH_ANSWER_TIMEOUT: Final = 10.0
#: A data frame waits this long for its RSSI/SNR frame.
META_WAIT: Final = 0.3
TX_RESULT_TIMEOUT: Final = 5.0
#: Dead-node detection. The node sends nothing while idle and a switched-off
#: node does not close the connection, so the system probes it: first after
#: KEEPALIVE_IDLE seconds of silence, then every KEEPALIVE_INTERVAL seconds;
#: after KEEPALIVE_COUNT unanswered probes (about 2 minutes in total) the
#: connection counts as lost. The system defaults (Linux: 2 h + 9 x 75 s)
#: would take over 2 hours.
KEEPALIVE_IDLE: Final = 60
KEEPALIVE_INTERVAL: Final = 15
KEEPALIVE_COUNT: Final = 4
#: Data sent to a dead node is given up after this long (Linux only); without
#: it the system retries for about 15 minutes.
USER_TIMEOUT_MS: Final = 120_000
_READ_SIZE: Final = 1024
_MAX_LINE: Final = 128


def set_keepalive(sock: socket.socket) -> None:
    """Let the system detect a switched-off node within about 2 minutes.

    Options a platform lacks are skipped (macOS names the idle time
    TCP_KEEPALIVE; TCP_USER_TIMEOUT exists on Linux only).
    """
    options = [
        (socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1),
        (socket.IPPROTO_TCP, getattr(socket, "TCP_KEEPIDLE", None), KEEPALIVE_IDLE),
        (socket.IPPROTO_TCP, getattr(socket, "TCP_KEEPALIVE", None), KEEPALIVE_IDLE),
        (socket.IPPROTO_TCP, getattr(socket, "TCP_KEEPINTVL", None), KEEPALIVE_INTERVAL),
        (socket.IPPROTO_TCP, getattr(socket, "TCP_KEEPCNT", None), KEEPALIVE_COUNT),
        (socket.IPPROTO_TCP, getattr(socket, "TCP_USER_TIMEOUT", None), USER_TIMEOUT_MS),
    ]
    for level, option, value in options:
        if option is None:
            continue
        with contextlib.suppress(OSError):
            sock.setsockopt(level, option, value)


class KissError(MeshComError):
    """Base class of KISS connection errors."""


class KissConnectionError(KissError):
    """The node could not be reached or closed the connection."""


class KissAuthError(KissError):
    """The node rejected the password."""


class KissAuthRequiredError(KissError):
    """The node asks for a password, but none is configured."""


class KissSendError(KissError):
    """The node did not accept a frame for transmission."""

    def __init__(self, status: int | None) -> None:
        super().__init__(f"send rejected: {status}")
        self.status = status


class KissConnection:
    """One TCP connection to a node's KISS interface."""

    def __init__(  # noqa: PLR0913  # all connection parameters, two keyword-only
        self,
        host: str,
        callsign: str,
        password: str | None,
        on_packet: Callable[[Packet], None],
        *,
        port: int = KISS_TCP_PORT,
        connect_timeout: float = 10.0,
    ) -> None:
        self.host = host
        self.port = port
        self.callsign = callsign
        self._password = password or None
        self._on_packet = on_packet
        self._connect_timeout = connect_timeout
        self._decoder = KissDecoder(callsign)
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._leftover = b""
        self._flush_handle: asyncio.TimerHandle | None = None
        self._tx_waiter: asyncio.Future[KissTxResult] | None = None
        self._send_lock = asyncio.Lock()
        self._sequence = secrets.randbelow(999)
        #: True if the node asked for and accepted the password.
        self.authenticated = False

    @property
    def invalid_frames(self) -> dict[str, int]:
        """Frames that could not be decoded, by reason."""
        return dict(self._decoder.invalid)

    async def connect(self) -> None:
        """Open the connection and authenticate if the node asks for it."""
        try:
            async with asyncio.timeout(self._connect_timeout):
                self._reader, self._writer = await asyncio.open_connection(self.host, self.port)
        except (OSError, TimeoutError) as err:
            raise KissConnectionError(type(err).__name__) from err
        sock = self._writer.get_extra_info("socket")
        if sock is not None:
            set_keepalive(sock)
        try:
            await self._handshake(self._reader, self._writer)
        except BaseException:
            await self.close()
            raise

    async def _handshake(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            async with asyncio.timeout(CHALLENGE_TIMEOUT):
                first = await reader.read(_READ_SIZE)
        except TimeoutError:
            first = b""  # no challenge: authentication is off on the node
        except OSError as err:  # pragma: no cover - reset during the handshake
            raise KissConnectionError(type(err).__name__) from err
        if not first.startswith(b"NONCE"):
            self._leftover = first
            return
        line, _, rest = first.partition(b"\n")
        nonce = parse_nonce(line + b"\n")
        if nonce is None:
            raise KissConnectionError("bad challenge")
        if self._password is None:
            raise KissAuthRequiredError("password required")
        writer.write(auth_response(self._password, nonce))
        answer = rest
        try:
            async with asyncio.timeout(AUTH_ANSWER_TIMEOUT):
                while b"\n" not in answer and len(answer) < _MAX_LINE:
                    chunk = await reader.read(_READ_SIZE)
                    if not chunk:
                        break
                    answer += chunk
        except (TimeoutError, OSError) as err:
            raise KissConnectionError("no answer") from err
        status, _, after = answer.partition(b"\n")
        status = status.strip()
        if status == b"OK":
            self.authenticated = True
            self._leftover = after
            return
        if status == b"FAIL":
            raise KissAuthError("password rejected")
        raise KissConnectionError("unexpected answer")

    async def run(self) -> None:
        """Read until the connection ends; raises :class:`KissConnectionError`."""
        if self._reader is None:
            raise KissConnectionError("not connected")
        if self._leftover:
            data, self._leftover = self._leftover, b""
            self._handle(data)
        try:
            while True:
                data = await self._reader.read(_READ_SIZE)
                if not data:
                    raise KissConnectionError("closed by node")
                self._handle(data)
        except OSError as err:  # pragma: no cover - platform dependent (RST vs. EOF)
            raise KissConnectionError(type(err).__name__) from err
        finally:
            self._flush()
            if self._tx_waiter is not None and not self._tx_waiter.done():
                self._tx_waiter.set_exception(KissConnectionError("closed"))

    def _handle(self, data: bytes) -> None:
        for item in self._decoder.feed(data):
            self._dispatch(item)
        if self._flush_handle is not None:
            self._flush_handle.cancel()
            self._flush_handle = None
        if self._decoder.has_pending:
            self._flush_handle = asyncio.get_running_loop().call_later(META_WAIT, self._flush)

    def _flush(self) -> None:
        self._flush_handle = None
        for item in self._decoder.flush():
            self._dispatch(item)

    def _dispatch(self, item: Packet | KissTxResult) -> None:
        if isinstance(item, KissTxResult):
            if self._tx_waiter is not None and not self._tx_waiter.done():
                self._tx_waiter.set_result(item)
            return
        self._on_packet(item)

    def _next_sequence(self) -> int:
        self._sequence = self._sequence % 999 + 1
        return self._sequence

    async def send_text(self, destination: str, text: str, *, direct: bool) -> Packet:
        """Send a message; returns the own packet once the node accepted it.

        The node does not echo messages from a KISS client, so the returned
        packet (with the node's message id) stands in for the echo.
        """
        if self._writer is None:
            raise KissConnectionError("not connected")
        async with self._send_lock:
            sequence = self._next_sequence() if direct else None
            frame = build_kiss_message(self.callsign, destination, text, sequence)
            loop = asyncio.get_running_loop()
            self._tx_waiter = loop.create_future()
            try:
                self._writer.write(frame)
                await self._writer.drain()
                async with asyncio.timeout(TX_RESULT_TIMEOUT):
                    result = await self._tx_waiter
            except TimeoutError as err:
                raise KissSendError(None) from err
            except OSError as err:  # pragma: no cover - write to a reset socket
                raise KissConnectionError(type(err).__name__) from err
            finally:
                self._tx_waiter = None
        if not result.ok or result.msg_id is None:
            raise KissSendError(result.status)
        packet = own_message_packet(self.callsign, destination, text, sequence, result.msg_id)
        self._on_packet(packet)
        return packet

    async def close(self) -> None:
        """Close the connection."""
        if self._flush_handle is not None:
            self._flush_handle.cancel()
            self._flush_handle = None
        writer, self._writer = self._writer, None
        self._reader = None
        if writer is not None:
            writer.close()
            with contextlib.suppress(OSError, ConnectionError):
                await writer.wait_closed()


__all__ = [
    "KissAuthError",
    "KissAuthRequiredError",
    "KissConnection",
    "KissConnectionError",
    "KissError",
    "KissSendError",
    "TxStatus",
]
