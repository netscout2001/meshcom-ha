"""Shared UDP listener for MeshCom nodes.

All nodes send to the same fixed destination port, so several config entries
share one socket per listening port. The hub assigns each datagram to a node
by its sender address and drops everything else (security concept C-05).

The external UDP interface has no authentication. The hub therefore:

* accepts datagrams only from registered node addresses,
* rate-limits every sender,
* parses strictly and never logs packet content (C-07, C-08),
* counts what it drops, so problems are visible in diagnostics.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from homeassistant.core import HomeAssistant, callback

from .aiomeshcom import InvalidPacketError, Packet, parse_datagram
from .aiomeshcom.const import EXT_UDP_PORT
from .const import DOMAIN, RATE_LIMIT_BURST, RATE_LIMIT_PER_SECOND

_LOGGER = logging.getLogger(__name__)

type PacketCallback = Callable[[Packet], None]


@dataclass(slots=True)
class _TokenBucket:
    tokens: float = RATE_LIMIT_BURST
    updated: float = field(default_factory=time.monotonic)

    def take(self) -> bool:
        now = time.monotonic()
        refill = (now - self.updated) * RATE_LIMIT_PER_SECOND
        self.tokens = min(RATE_LIMIT_BURST, self.tokens + refill)
        self.updated = now
        if self.tokens < 1:
            return False
        self.tokens -= 1
        return True


class _Protocol(asyncio.DatagramProtocol):
    def __init__(self, hub: UdpHub) -> None:
        self._hub = hub

    def datagram_received(self, data: bytes, addr: tuple[str | Any, int]) -> None:
        self._hub.handle_datagram(data, str(addr[0]))

    def error_received(self, exc: Exception) -> None:
        _LOGGER.debug("UDP error on port %s: %s", self._hub.port, type(exc).__name__)


class UdpHub:
    """One UDP socket, shared by all nodes that send to this port."""

    def __init__(self, port: int) -> None:
        self.port = port
        self._transport: asyncio.DatagramTransport | None = None
        self._listeners: dict[str, list[PacketCallback]] = {}
        self._buckets: dict[str, _TokenBucket] = {}
        self.dropped: Counter[str] = Counter()
        self.accepted = 0

    async def async_start(self) -> None:
        """Open the socket. Raises OSError if the port is in use."""
        loop = asyncio.get_running_loop()
        transport, _ = await loop.create_datagram_endpoint(
            lambda: _Protocol(self),
            # The node sends from the LAN to a fixed port. Only registered node
            # addresses are accepted (see handle_datagram); everything else is
            # dropped before parsing.
            local_addr=("0.0.0.0", self.port),  # noqa: S104  # nosec B104
        )
        self._transport = transport

    def close(self) -> None:
        """Close the socket."""
        if self._transport is not None:
            self._transport.close()
            self._transport = None

    @property
    def idle(self) -> bool:
        """True if no node is registered any more."""
        return not self._listeners

    @callback
    def register(self, host: str, listener: PacketCallback) -> Callable[[], None]:
        """Deliver packets from ``host`` to ``listener``. Returns an unregister function."""
        self._listeners.setdefault(host, []).append(listener)

        @callback
        def _unregister() -> None:
            listeners = self._listeners.get(host, [])
            if listener in listeners:
                listeners.remove(listener)
            if not listeners:
                self._listeners.pop(host, None)
                self._buckets.pop(host, None)

        return _unregister

    @callback
    def handle_datagram(self, data: bytes, host: str) -> None:
        """Validate one datagram and hand it to the node registered for ``host``."""
        listeners = self._listeners.get(host)
        if not listeners:
            # Unknown sender. Not logged per packet, so a flood cannot fill the log.
            self.dropped["unknown_sender"] += 1
            return
        bucket = self._buckets.setdefault(host, _TokenBucket())
        if not bucket.take():
            self.dropped["rate_limit"] += 1
            return
        try:
            packet = parse_datagram(data)
        except InvalidPacketError as err:
            self.dropped[err.reason] += 1
            _LOGGER.debug("Dropped datagram from %s: %s", host, err.reason)
            return
        self.accepted += 1
        for listener in list(listeners):
            listener(packet)

    def send(self, host: str, data: bytes) -> None:
        """Send a datagram to a node's external UDP port."""
        if self._transport is None:
            raise ConnectionError("UDP socket is closed")
        self._transport.sendto(data, (host, EXT_UDP_PORT))

    def diagnostics(self) -> dict[str, Any]:
        """Counters for diagnostics (no packet content)."""
        return {
            "port": self.port,
            "registered_nodes": len(self._listeners),
            "accepted": self.accepted,
            "dropped": dict(self.dropped),
        }


_HUBS_KEY = f"{DOMAIN}_hubs"
_LOCK_KEY = f"{DOMAIN}_hubs_lock"


async def async_acquire_hub(hass: HomeAssistant, port: int) -> UdpHub:
    """Return the running hub for ``port``, starting it if needed."""
    lock: asyncio.Lock = hass.data.setdefault(_LOCK_KEY, asyncio.Lock())
    async with lock:
        hubs: dict[int, UdpHub] = hass.data.setdefault(_HUBS_KEY, {})
        hub = hubs.get(port)
        if hub is None:
            hub = UdpHub(port)
            await hub.async_start()
            hubs[port] = hub
        return hub


@callback
def async_release_hub(hass: HomeAssistant, hub: UdpHub) -> None:
    """Close the hub when no node uses it any more."""
    if not hub.idle:
        return
    hubs: dict[int, UdpHub] = hass.data.get(_HUBS_KEY, {})
    if hubs.get(hub.port) is hub:
        del hubs[hub.port]
    hub.close()
