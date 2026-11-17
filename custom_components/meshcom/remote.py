"""Remote management of other nodes over LoRa (issue #50).

Home Assistant signs ``RM1`` commands with the target node's password and
hands them to the own node as a direct message; the target answers with a
signed reply that comes back like any other message. The own node never
learns the target's password.

Rules:

* one command at a time per target, at least 10 s apart (firmware rate
  limit with strict security),
* every command uses a counter above the target's high-water mark. The
  counter is stored; when it is unknown or a command got no answer, a
  ``sync`` asks the target for its mark first,
* a reply counts only with the expected counter and a valid tag; a missing
  reply is "unknown", never "off",
* nothing is polled: frames go out only when a user or an automation asks.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, Final

from homeassistant.const import CONF_PASSWORD
from homeassistant.core import Context, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .aiomeshcom import RemoteManagementPacket, is_callsign
from .aiomeshcom.errors import InvalidOutgoingError
from .aiomeshcom.rm import (
    MAX_COUNTER,
    NO_ANSWER_SECONDS,
    RATE_INTERVAL_SECONDS,
    TOGGLES,
    RemoteStatus,
    build_command,
    derive_key,
    parse_status,
    parse_sync,
    verify_reply,
)
from .const import CONF_CALLSIGN, DOMAIN, SUBENTRY_REMOTE, signal_remote

if TYPE_CHECKING:
    from . import MeshComConfigEntry

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION: Final = 1
_SAVE_DELAY: Final = 5

type SendControl = Callable[[str, str, Context | None], Any]


@dataclass(slots=True)
class RemoteNode:
    """State of one managed node as far as its answers tell."""

    subentry_id: str
    callsign: str
    key: bytes = field(repr=False)
    status: RemoteStatus | None = None
    switches: dict[str, bool] = field(default_factory=dict)
    tx_power: int | None = None
    led: str | None = None
    reachable: bool | None = None
    last_answer: datetime | None = None
    last_result: str | None = None
    status_read: datetime | None = None
    busy: bool = False
    need_sync: bool = True
    lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)
    last_sent: float = 0.0


class RemoteManager:
    """All remote nodes managed through one own node."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: MeshComConfigEntry,
        own_callsign: str,
        send: SendControl,
    ) -> None:
        self.hass = hass
        self.entry = entry
        self.own_callsign = own_callsign
        self._send = send
        self.remotes: dict[str, RemoteNode] = {}
        self._pending: dict[tuple[str, int], asyncio.Future[str]] = {}
        self._counters: dict[str, int] = {}
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}.remote"
        )
        self.replies_ignored = 0

    async def async_load(self) -> None:
        """Read the stored counters and the configured remote nodes."""
        data = await self._store.async_load() or {}
        counters = data.get("counters", {})
        if isinstance(counters, dict):
            self._counters = {
                call: value
                for call, value in counters.items()
                if isinstance(call, str) and isinstance(value, int) and 0 <= value <= MAX_COUNTER
            }
        for subentry in self.entry.subentries.values():
            if subentry.subentry_type != SUBENTRY_REMOTE:
                continue
            callsign = subentry.data.get(CONF_CALLSIGN)
            password = subentry.data.get(CONF_PASSWORD)
            if not isinstance(callsign, str) or not is_callsign(callsign):
                continue
            try:
                key = derive_key(password if isinstance(password, str) else "")
            except InvalidOutgoingError:
                _LOGGER.warning("%s: remote node without a usable password", self.entry.title)
                continue
            self.remotes[subentry.subentry_id] = RemoteNode(
                subentry_id=subentry.subentry_id,
                callsign=callsign,
                key=key,
                need_sync=callsign not in self._counters,
            )

    async def async_save_now(self) -> None:
        """Write the counters (on unload)."""
        await self._store.async_save(self._data())

    async def async_remove(self) -> None:
        """Delete the stored counters (entry removed)."""
        await self._store.async_remove()

    def _data(self) -> dict[str, Any]:
        return {"counters": dict(self._counters)}

    @callback
    def handle_packet(self, packet: RemoteManagementPacket) -> None:
        """Hand a received reply to the command waiting for it."""
        if not packet.is_reply or packet.destination != self.own_callsign:
            return
        sender = packet.path.originator
        for remote in self.remotes.values():
            if remote.callsign != sender:
                continue
            future = self._pending.get((sender, packet.counter))
            result = None
            if future is not None and not future.done():
                result = verify_reply(
                    remote.key,
                    packet.text,
                    target=remote.callsign,
                    commander=self.own_callsign,
                    counter=packet.counter,
                )
            if result is None:
                # Late, duplicate, forged or for another client: ignored.
                self.replies_ignored += 1
                return
            future.set_result(result)  # type: ignore[union-attr]
            return

    @callback
    def _changed(self, remote: RemoteNode) -> None:
        async_dispatcher_send(self.hass, signal_remote(self.entry.entry_id, remote.subentry_id))

    async def async_command(
        self, subentry_id: str, cmd: str, args: str = "", context: Context | None = None
    ) -> str:
        """Run one command on a remote node and return its ``ok ...`` result."""
        remote = self.remotes.get(subentry_id)
        if remote is None:
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="rm_unknown")
        async with remote.lock:
            remote.busy = True
            self._changed(remote)
            try:
                if remote.need_sync:
                    await self._async_sync(remote, context)
                result = await self._async_exchange(remote, cmd, args, context)
            finally:
                remote.busy = False
                self._changed(remote)
        if result.startswith("err"):
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="rm_refused",
                translation_placeholders={"reason": result[4:] or "?"},
            )
        self._apply(remote, cmd, args, result)
        self._changed(remote)
        return result

    async def _async_sync(self, remote: RemoteNode, context: Context | None) -> None:
        result = await self._async_exchange(remote, "sync", "", context, counter=0)
        mark = parse_sync(result)
        if mark is None:
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="rm_no_answer")
        # Never step back below what this side already used.
        self._counters[remote.callsign] = max(mark, self._counters.get(remote.callsign, 0))
        self._store.async_delay_save(self._data, _SAVE_DELAY)
        remote.need_sync = False

    async def _async_exchange(
        self,
        remote: RemoteNode,
        cmd: str,
        args: str,
        context: Context | None,
        *,
        counter: int | None = None,
    ) -> str:
        """Send one frame and wait for its verified reply (caller holds the lock)."""
        if counter is None:
            counter = self._counters.get(remote.callsign, 0) + 1
            if counter > MAX_COUNTER:
                raise HomeAssistantError(
                    translation_domain=DOMAIN, translation_key="rm_counter_exhausted"
                )
        text = build_command(
            remote.key,
            target=remote.callsign,
            commander=self.own_callsign,
            counter=counter,
            cmd=cmd,
            args=args,
        )
        wait = remote.last_sent + RATE_INTERVAL_SECONDS - time.monotonic()
        if wait > 0:
            await asyncio.sleep(wait)
        future: asyncio.Future[str] = self.hass.loop.create_future()
        self._pending[(remote.callsign, counter)] = future
        try:
            await self._send(remote.callsign, text, context)
            remote.last_sent = time.monotonic()
            if counter:
                # Used once, never again: a higher counter is always valid.
                self._counters[remote.callsign] = counter
                self._store.async_delay_save(self._data, _SAVE_DELAY)
            try:
                async with asyncio.timeout(NO_ANSWER_SECONDS):
                    result = await future
            except TimeoutError as err:
                # Silent rejects (replay, rate, lockout) look exactly like
                # this: sync before the next command.
                remote.need_sync = True
                remote.reachable = False
                raise HomeAssistantError(
                    translation_domain=DOMAIN, translation_key="rm_no_answer"
                ) from err
        finally:
            self._pending.pop((remote.callsign, counter), None)
        remote.reachable = True
        remote.last_answer = dt_util.utcnow()
        remote.last_result = result
        return result

    @callback
    def _apply(self, remote: RemoteNode, cmd: str, args: str, result: str) -> None:
        """Take over what an ``ok`` result confirms; no extra frame is sent."""
        if cmd == "status":
            status = parse_status(result)
            if status is not None:
                remote.status = status
                remote.status_read = remote.last_answer
                remote.switches = dict(status.switches)
                remote.tx_power = status.tx_power
                if "led" in status.switches:
                    remote.led = "on" if status.switches["led"] else "off"
        elif cmd in TOGGLES and result == f"ok {cmd}={args}":
            remote.switches[cmd] = args == "on"
        elif cmd == "txpower" and result == f"ok txpower={args}":
            remote.tx_power = int(args)
        elif cmd == "led" and result == f"ok led={args}":
            remote.led = args
        elif cmd == "reboot":
            # Everything read before the restart is stale now.
            remote.switches = {}
            remote.tx_power = None
            remote.led = None

    def diagnostics(self) -> dict[str, Any]:
        """Counts only: no callsigns, no keys."""
        return {
            "remote_nodes": len(self.remotes),
            "pending": len(self._pending),
            "replies_ignored": self.replies_ignored,
        }
