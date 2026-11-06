"""Config flow for MeshCom.

The node is identified by a packet it sends itself. The flow listens on the
UDP port and waits until the node at the given address sends its own
position beacon or message. From that packet it learns the callsign and the
node id, which becomes the unique id (not the IP address).
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST

from .aiomeshcom import Packet, PositionPacket, SourceType, TextMessagePacket
from .const import (
    CONF_CALLSIGN,
    CONF_LISTEN_PORT,
    CONF_NODE_ID,
    DEFAULT_LISTEN_PORT,
    DOMAIN,
    SETUP_WAIT_TIMEOUT,
)
from .hub import async_acquire_hub, async_release_hub

_LOGGER = logging.getLogger(__name__)


def _valid_host(value: str) -> bool:
    """Only private IPv4 literals (security concept C-15).

    A hostname or public address would send setup traffic, and later the web
    login, to a place the user did not mean. The node's web guard also
    rejects hostnames.
    """
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    return (
        address.version == 4
        and (address.is_private or address.is_link_local)
        and not (address.is_loopback or address.is_unspecified or address.is_multicast)
    )


class MeshComConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for MeshCom."""

    VERSION = 1
    MINOR_VERSION = 1

    def __init__(self) -> None:
        self._host = ""
        self._port = DEFAULT_LISTEN_PORT
        self._wait_task: asyncio.Task[tuple[str, int]] | None = None
        self._found: tuple[str, int] | None = None

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask for the node address and the listening port."""
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            if not _valid_host(host):
                errors[CONF_HOST] = "invalid_host"
            else:
                self._async_abort_entries_match({CONF_HOST: host})
                self._host = host
                self._port = user_input[CONF_LISTEN_PORT]
                self._wait_task = None
                return await self.async_step_wait()
        schema = vol.Schema(
            {
                vol.Required(CONF_HOST, default=self._host): str,
                vol.Required(CONF_LISTEN_PORT, default=self._port): vol.All(
                    vol.Coerce(int), vol.Range(min=1024, max=65535)
                ),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def _async_wait_for_node(self) -> tuple[str, int]:
        """Wait for an own packet of the node. Returns (callsign, node id)."""
        hub = await async_acquire_hub(self.hass, self._port)
        future: asyncio.Future[tuple[str, int]] = self.hass.loop.create_future()

        def _listener(packet: Packet) -> None:
            if (
                isinstance(packet, (PositionPacket, TextMessagePacket))
                and packet.source_type is SourceType.NODE
                and not future.done()
            ):
                future.set_result((packet.path.originator, packet.msg_id.node_id))

        unregister = hub.register(self._host, _listener)
        try:
            async with asyncio.timeout(SETUP_WAIT_TIMEOUT):
                return await future
        finally:
            unregister()
            async_release_hub(self.hass, hub)

    async def async_step_wait(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Show progress while waiting for the node."""
        if self._wait_task is None:
            self._wait_task = self.hass.async_create_task(self._async_wait_for_node())
        if not self._wait_task.done():
            return self.async_show_progress(
                step_id="wait",
                progress_action="wait_for_node",
                progress_task=self._wait_task,
                description_placeholders={"host": self._host, "port": str(self._port)},
            )
        try:
            self._found = self._wait_task.result()
        except TimeoutError:
            # TimeoutError is a subclass of OSError, so it must be caught first.
            return self.async_show_progress_done(next_step_id="no_packet")
        except OSError:
            return self.async_show_progress_done(next_step_id="port_unavailable")
        return self.async_show_progress_done(next_step_id="finish")

    async def async_step_port_unavailable(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """The UDP port could not be opened."""
        return self.async_abort(
            reason="port_unavailable", description_placeholders={"port": str(self._port)}
        )

    async def async_step_no_packet(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Nothing arrived in time; offer to try again."""
        if user_input is not None:
            self._wait_task = None
            return await self.async_step_user()
        return self.async_show_form(
            step_id="no_packet",
            description_placeholders={"host": self._host, "port": str(self._port)},
        )

    async def async_step_finish(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Create the entry."""
        if self._found is None:
            return self.async_abort(reason="unknown")
        callsign, node_id = self._found
        await self.async_set_unique_id(f"{node_id:06x}")
        self._abort_if_unique_id_configured(updates={CONF_HOST: self._host})
        return self.async_create_entry(
            title=callsign,
            data={
                CONF_HOST: self._host,
                CONF_LISTEN_PORT: self._port,
                CONF_CALLSIGN: callsign,
                CONF_NODE_ID: node_id,
            },
        )
