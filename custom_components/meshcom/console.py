"""Interactive net console of the node (issue #54).

Opened on demand from the panel and closed again as soon as nobody looks
at it, after an idle time, or when the node ends the session. The node
serves one console client and a new login replaces the running one, so a
permanent session would fight with every other login.

Security:

* only administrators reach it (websocket commands are admin-only),
* commands are single validated lines; risky ones need an explicit
  confirmation, checked here and not only in the browser,
* the output may contain secrets in clear text (BT PIN, WLAN SSID): it is
  kept in memory only, never logged, never stored, never in diagnostics.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections import deque
from collections.abc import Callable
from datetime import timedelta
from typing import TYPE_CHECKING, Any, Final

from homeassistant.const import CONF_HOST
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.event import async_call_later

from .aiomeshcom.errors import InvalidOutgoingError
from .aiomeshcom.netconsole import (
    ConsoleAuthError,
    ConsoleAuthRequiredError,
    ConsoleError,
    ConsoleRefusedError,
    ConsoleUnreachableError,
    NetConsole,
    RadioInfo,
    command_risk,
    parse_radio_info,
    validate_command,
)
from .const import CONF_KISS_PASSWORD, CONF_NODE_PASSWORD, DOMAIN

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

_LOGGER = logging.getLogger(__name__)

IDLE_TIMEOUT: Final = timedelta(minutes=10)
#: How long to wait for the radio line of "--info".
RADIO_INFO_TIMEOUT: Final = 15
SCROLLBACK: Final = 500

STATE_DISCONNECTED: Final = "disconnected"
STATE_CONNECTING: Final = "connecting"
STATE_CONNECTED: Final = "connected"
STATE_CLOSED_BY_NODE: Final = "closed_by_node"
STATE_IDLE: Final = "idle_timeout"
STATE_REFUSED: Final = "refused"
STATE_UNREACHABLE: Final = "unreachable"
STATE_AUTH_FAILED: Final = "auth_failed"
STATE_AUTH_REQUIRED: Final = "auth_required"
STATE_PROTOCOL: Final = "protocol_error"

_ERROR_STATES: Final = {
    ConsoleRefusedError: STATE_REFUSED,
    ConsoleUnreachableError: STATE_UNREACHABLE,
    ConsoleAuthError: STATE_AUTH_FAILED,
    ConsoleAuthRequiredError: STATE_AUTH_REQUIRED,
}

type ConsoleListener = Callable[[str, dict[str, Any]], None]


def node_password(entry: ConfigEntry) -> str | None:
    """The node's ``--passwd``: its own field, or the KISS password (same secret)."""
    password = entry.data.get(CONF_NODE_PASSWORD) or entry.data.get(CONF_KISS_PASSWORD)
    return password if isinstance(password, str) and password else None


class ConsoleSession:
    """The console of one node; at most one connection at a time."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.state = STATE_DISCONNECTED
        self.open_access = False
        self.lines: deque[str] = deque(maxlen=SCROLLBACK)
        self._console: NetConsole | None = None
        self._task: asyncio.Task[None] | None = None
        self._listeners: list[ConsoleListener] = []
        self._idle: CALLBACK_TYPE | None = None
        self._lock = asyncio.Lock()

    def snapshot(self) -> dict[str, Any]:
        """State and scrollback for a new viewer."""
        return {"state": self.state, "open_access": self.open_access, "lines": list(self.lines)}

    @callback
    def async_subscribe(self, listener: ConsoleListener) -> CALLBACK_TYPE:
        """Receive ``line`` and ``state`` events; the last viewer leaving closes the session."""
        self._listeners.append(listener)

        @callback
        def _remove() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)
            if not self._listeners:
                self.hass.async_create_task(self.async_disconnect(), f"{DOMAIN} console close")

        return _remove

    @callback
    def _emit(self, kind: str, data: dict[str, Any]) -> None:
        for listener in list(self._listeners):
            listener(kind, data)

    @callback
    def _set_state(self, state: str) -> None:
        self.state = state
        self._emit("state", {"state": state, "open_access": self.open_access})

    @callback
    def _on_line(self, line: str) -> None:
        # Never logged: the output may carry secrets.
        self.lines.append(line)
        self._emit("line", {"line": line})

    async def async_connect(self) -> None:
        """Open the session if it is not open yet."""
        async with self._lock:
            if self._console is not None and self._console.connected:
                return
            self.open_access = False
            self._set_state(STATE_CONNECTING)
            console = NetConsole(
                self.entry.data[CONF_HOST], node_password(self.entry), self._on_line
            )
            try:
                await console.connect()
            except ConsoleError as err:
                self._set_state(_ERROR_STATES.get(type(err), STATE_PROTOCOL))
                _LOGGER.info("%s: console login failed (%s)", self.entry.title, self.state)
                return
            self._console = console
            self.open_access = console.open_access
            self._set_state(STATE_CONNECTED)
            _LOGGER.info("%s: console opened", self.entry.title)
            self._touch()
            self._task = self.entry.async_create_background_task(
                self.hass, self._async_run(console), f"{DOMAIN} console"
            )

    async def _async_run(self, console: NetConsole) -> None:
        await console.run()
        if self._console is console:
            self._console = None
            self._cancel_idle()
            self._set_state(STATE_CLOSED_BY_NODE)
            _LOGGER.info("%s: console closed by the node", self.entry.title)

    async def async_send(self, command: str, *, confirm: bool = False) -> None:
        """Send one command line; risky commands need ``confirm``."""
        try:
            line = validate_command(command)
        except InvalidOutgoingError as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="console_invalid_command"
            ) from err
        risk = command_risk(line)
        if risk is not None and not confirm:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="console_confirm",
                translation_placeholders={"risk": risk},
            )
        console = self._console
        if console is None or not console.connected:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="console_not_connected"
            )
        try:
            await console.send(line)
        except (ConsoleError, OSError) as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="console_not_connected"
            ) from err
        # Only the command word is logged; arguments may be passwords.
        _LOGGER.info("%s: console command %s", self.entry.title, line.split(" ", 1)[0])
        self._touch()

    async def async_read_radio_info(self) -> RadioInfo:
        """Run "--info" and read the radio settings from its output.

        Uses the open session if the console tab has one; otherwise it logs
        in for this and closes again, which ends any other console client
        (the node serves one).
        """
        lines: list[str] = []
        done = asyncio.Event()

        @callback
        def _collect(kind: str, data: dict[str, Any]) -> None:
            if kind == "line":
                lines.append(data["line"])
                if parse_radio_info((data["line"],)) is not None:
                    done.set()

        remove = self.async_subscribe(_collect)
        try:
            await self.async_connect()
            if self.state != STATE_CONNECTED:
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="radio_read_failed",
                    translation_placeholders={"state": self.state},
                )
            await self.async_send("--info")
            try:
                async with asyncio.timeout(RADIO_INFO_TIMEOUT):
                    await done.wait()
            except TimeoutError as err:
                raise HomeAssistantError(
                    translation_domain=DOMAIN, translation_key="radio_read_no_answer"
                ) from err
        finally:
            # The last viewer leaving closes a session opened just for this.
            remove()
        info = parse_radio_info(lines)
        if info is None:  # pragma: no cover - a line just parsed
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="radio_read_no_answer"
            )
        return info

    async def async_disconnect(self, state: str = STATE_DISCONNECTED) -> None:
        """Close the session (idempotent)."""
        self._cancel_idle()
        console, self._console = self._console, None
        task, self._task = self._task, None
        if console is not None:
            await console.close()
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        if console is not None or self.state == STATE_CONNECTING:
            self._set_state(state)

    @callback
    def _touch(self) -> None:
        self._cancel_idle()
        self._idle = async_call_later(self.hass, IDLE_TIMEOUT, self._idle_expired)

    @callback
    def _cancel_idle(self) -> None:
        if self._idle is not None:
            self._idle()
            self._idle = None

    @callback
    def _idle_expired(self, _now: Any) -> None:
        self._idle = None
        self.hass.async_create_task(self.async_disconnect(STATE_IDLE), f"{DOMAIN} console idle")
