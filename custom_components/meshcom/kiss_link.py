"""KISS-over-TCP access path of one node.

Keeps one connection open (the node serves a single client), reconnects
with growing waits, starts reauthentication when the node rejects the
password, and warns when the node does not ask for one (anyone in the
network could then connect and, with ``--kiss tx on``, transmit under the
node's callsign).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING

from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .aiomeshcom import is_callsign
from .aiomeshcom.kiss import TxStatus
from .aiomeshcom.kiss_client import (
    KissAuthError,
    KissAuthRequiredError,
    KissConnection,
    KissConnectionError,
    KissSendError,
)
from .const import (
    CONF_CALLSIGN,
    CONF_KISS_PASSWORD,
    CONF_KISS_PORT,
    DOMAIN,
    ISSUE_KISS_AUTH_OFF,
    KISS_RECONNECT_DELAYS,
    signal_update,
)

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

    from .node import MeshComNode

_LOGGER = logging.getLogger(__name__)

_SEND_ERRORS = {
    TxStatus.TX_OFF: "kiss_tx_off",
    TxStatus.BAD_CALL: "kiss_bad_call",
    TxStatus.RATE_LIMIT: "rate_limited_node",
}


class KissLink:
    """Connection manager for one node."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, node: MeshComNode) -> None:
        self.hass = hass
        self.entry = entry
        self.node = node
        self.connected = False
        self.authenticated = False
        self.connects = 0
        self._connection: KissConnection | None = None
        self._task: asyncio.Task[None] | None = None
        self._issue_id = f"{ISSUE_KISS_AUTH_OFF}_{entry.entry_id}"
        self._logged_unavailable = False

    def _new_connection(self) -> KissConnection:
        return KissConnection(
            self.entry.data[CONF_HOST],
            self.entry.data[CONF_CALLSIGN],
            self.entry.data.get(CONF_KISS_PASSWORD),
            self.node.handle_packet,
            port=self.entry.data[CONF_KISS_PORT],
        )

    @callback
    def async_start(self) -> None:
        """Start the connection loop in the background."""
        self._task = self.entry.async_create_background_task(
            self.hass, self._async_loop(), f"{DOMAIN} kiss {self.entry.title}"
        )

    async def async_stop(self) -> None:
        """Stop the loop and close the connection."""
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        if self._connection is not None:
            await self._connection.close()
            self._connection = None
        self._set_connected(False)

    def _set_connected(self, connected: bool) -> None:
        if connected != self.connected:
            self.connected = connected
            async_dispatcher_send(self.hass, signal_update(self.entry.entry_id))

    async def _async_loop(self) -> None:
        attempt = 0
        while True:
            connection = self._new_connection()
            try:
                await connection.connect()
            except (KissAuthError, KissAuthRequiredError):
                _LOGGER.warning("%s: the node rejected the KISS login", self.entry.title)
                self.entry.async_start_reauth(self.hass)
                return
            except KissConnectionError:
                if not self._logged_unavailable:
                    # Logged once; a mobile node is often out of reach.
                    _LOGGER.info("%s: KISS interface not reachable", self.entry.title)
                    self._logged_unavailable = True
            else:
                attempt = 0
                self._connection = connection
                self.authenticated = connection.authenticated
                self.connects += 1
                if self._logged_unavailable:
                    _LOGGER.info("%s: KISS interface reachable again", self.entry.title)
                    self._logged_unavailable = False
                self._update_auth_issue()
                self._set_connected(True)
                try:
                    await connection.run()
                except KissConnectionError:
                    pass
                finally:
                    self._connection = None
                    self._set_connected(False)
                    await connection.close()
            delay = KISS_RECONNECT_DELAYS[min(attempt, len(KISS_RECONNECT_DELAYS) - 1)]
            attempt += 1
            await asyncio.sleep(delay)

    def _update_auth_issue(self) -> None:
        if self.authenticated:
            ir.async_delete_issue(self.hass, DOMAIN, self._issue_id)
            return
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            self._issue_id,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=ISSUE_KISS_AUTH_OFF,
            translation_placeholders={"node": self.entry.title},
        )

    async def async_send_text(self, destination: str, text: str) -> None:
        """Send through the node; errors become Home Assistant errors."""
        connection = self._connection
        if connection is None or not self.connected:
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="kiss_offline")
        direct = is_callsign(destination)
        try:
            await connection.send_text(destination, text, direct=direct)
        except KissSendError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key=_SEND_ERRORS.get(err.status or 0, "send_failed"),
            ) from err
        except KissConnectionError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="kiss_offline"
            ) from err

    def diagnostics(self) -> dict[str, object]:
        """Connection state without addresses or secrets."""
        connection = self._connection
        return {
            "connected": self.connected,
            "authenticated": self.authenticated,
            "connects": self.connects,
            "invalid_frames": connection.invalid_frames if connection else {},
        }
