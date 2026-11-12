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
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_HOST, CONF_PASSWORD
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .aiomeshcom import (
    Packet,
    PositionPacket,
    SourceType,
    TextMessagePacket,
    is_callsign,
    is_group,
)
from .aiomeshcom.kiss import KISS_TCP_PORT, MAX_KISS_PASSWORD
from .aiomeshcom.kiss_client import (
    KissAuthError,
    KissAuthRequiredError,
    KissConnection,
    KissConnectionError,
)
from .aiomeshcom.webapi import (
    AUTH_HMAC,
    MeshComWebClient,
    WebApiError,
    WebAuthError,
    WebDowngradeError,
    WebThrottledError,
)
from .const import (
    ACCESS_KISS,
    ACCESS_UDP,
    CONF_ACCESS,
    CONF_CALLSIGN,
    CONF_GROUPS,
    CONF_HIDE_FOREIGN_GROUPS,
    CONF_INACTIVE_MINUTES,
    CONF_KISS_PASSWORD,
    CONF_KISS_PORT,
    CONF_LISTEN_PORT,
    CONF_NEIGHBOUR_LOST_HOURS,
    CONF_NODE_ID,
    CONF_RADIO_STATS,
    CONF_SEND_USERS,
    CONF_STATION_MAX,
    CONF_STATION_MODE,
    CONF_STATION_STALE_DAYS,
    CONF_WEB_AUTH,
    DEFAULT_HIDE_FOREIGN_GROUPS,
    DEFAULT_INACTIVE_MINUTES,
    DEFAULT_LISTEN_PORT,
    DEFAULT_NEIGHBOUR_LOST_HOURS,
    DEFAULT_RADIO_STATS,
    DEFAULT_STATION_MAX,
    DEFAULT_STATION_STALE_DAYS,
    DOMAIN,
    INACTIVE_MINUTES_RANGE,
    NEIGHBOUR_LOST_HOURS_MAX,
    SETUP_WAIT_TIMEOUT,
    STATION_MAX_LIMIT,
    STATION_MODES,
    STATION_STALE_DAYS_LIMIT,
)
from .hub import async_acquire_hub, async_release_hub
from .migration import callsign_node_id
from .stations import station_mode

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
    #: 1.2: node id derived from the callsign for both access paths.
    MINOR_VERSION = 2

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> MeshComOptionsFlow:
        """Options: groups and who may transmit."""
        return MeshComOptionsFlow()

    def __init__(self) -> None:
        self._host = ""
        self._port = DEFAULT_LISTEN_PORT
        self._wait_task: asyncio.Task[tuple[str, int]] | None = None
        self._found: tuple[str, int] | None = None
        #: Extra entry data of the KISS access path.
        self._kiss: dict[str, Any] = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Choose the access path."""
        return self.async_show_menu(step_id="user", menu_options=[ACCESS_UDP, ACCESS_KISS])

    async def async_step_kiss(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """KISS over TCP: address, port, own callsign and the node's --passwd."""
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            callsign = user_input[CONF_CALLSIGN].strip().upper()
            password = user_input.get(CONF_KISS_PASSWORD) or None
            if not _valid_host(host):
                errors[CONF_HOST] = "invalid_host"
            elif not is_callsign(callsign):
                errors[CONF_CALLSIGN] = "invalid_callsign"
            elif password is not None and not _valid_kiss_password(password):
                errors[CONF_KISS_PASSWORD] = "invalid_kiss_password"
            else:
                self._async_abort_entries_match({CONF_HOST: host})
                self._async_abort_entries_match({CONF_CALLSIGN: callsign})
                errors = await _async_validate_kiss(
                    host, user_input[CONF_KISS_PORT], callsign, password
                )
                if not errors:
                    node_id = callsign_node_id(callsign)
                    await self.async_set_unique_id(f"{node_id:06x}")
                    self._abort_if_unique_id_configured()
                    self._host = host
                    self._found = (callsign, node_id)
                    self._kiss = {
                        CONF_ACCESS: ACCESS_KISS,
                        CONF_KISS_PORT: user_input[CONF_KISS_PORT],
                    }
                    if password:
                        self._kiss[CONF_KISS_PASSWORD] = password
                    return await self.async_step_web()
        defaults = user_input or {}
        schema = vol.Schema(
            {
                vol.Required(CONF_HOST, default=defaults.get(CONF_HOST, "")): str,
                vol.Required(
                    CONF_KISS_PORT, default=defaults.get(CONF_KISS_PORT, KISS_TCP_PORT)
                ): vol.All(vol.Coerce(int), vol.Range(min=1, max=65535)),
                vol.Required(CONF_CALLSIGN, default=defaults.get(CONF_CALLSIGN, "")): str,
                vol.Optional(CONF_KISS_PASSWORD): TextSelector(
                    TextSelectorConfig(type=TextSelectorType.PASSWORD)
                ),
            }
        )
        return self.async_show_form(step_id="kiss", data_schema=schema, errors=errors)

    async def async_step_udp(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
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
        return self.async_show_form(step_id="udp", data_schema=schema, errors=errors)

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
            return await self.async_step_udp()
        return self.async_show_form(
            step_id="no_packet",
            description_placeholders={"host": self._host, "port": str(self._port)},
        )

    async def async_step_finish(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Node identified; continue with the web password."""
        if self._found is None:
            return self.async_abort(reason="unknown")
        callsign, _ = self._found
        # Same id for UDP and KISS: switching the access path keeps the
        # device and its entities.
        node_id = callsign_node_id(callsign)
        self._found = (callsign, node_id)
        await self.async_set_unique_id(f"{node_id:06x}")
        self._abort_if_unique_id_configured(updates={CONF_HOST: self._host})
        # The same node may already be set up through KISS.
        self._async_abort_entries_match({CONF_CALLSIGN: callsign})
        return await self.async_step_web()

    async def async_step_web(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Optional web password of the node (``--webpwd``)."""
        errors: dict[str, str] = {}
        if user_input is not None and self._found is not None:
            password = user_input.get(CONF_PASSWORD) or None
            errors, method = await _async_validate_web(self.hass, self._host, password)
            if not errors:
                callsign, node_id = self._found
                data: dict[str, Any] = {
                    CONF_HOST: self._host,
                    CONF_CALLSIGN: callsign,
                    CONF_NODE_ID: node_id,
                    **(self._kiss or {CONF_LISTEN_PORT: self._port}),
                }
                if password:
                    data[CONF_PASSWORD] = password
                if method == AUTH_HMAC:
                    data[CONF_WEB_AUTH] = AUTH_HMAC
                return self.async_create_entry(title=callsign, data=data)
        return self.async_show_form(step_id="web", data_schema=_PASSWORD_SCHEMA, errors=errors)

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """The node rejected the stored web password."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the current web password."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            password = user_input.get(CONF_PASSWORD) or None
            errors, method = await _async_validate_web(
                self.hass,
                entry.data[CONF_HOST],
                password,
                allow_legacy=entry.data.get(CONF_WEB_AUTH) != AUTH_HMAC,
            )
            data = _with_password(entry.data, password, method)
            if not errors and _is_kiss(entry):
                errors, data = await _async_check_kiss_password(entry, user_input, data)
            if not errors:
                return self.async_update_reload_and_abort(entry, data=data)
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=_password_schema(entry),
            errors=errors,
            description_placeholders={"node": entry.title},
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the web password of an existing node."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            password = user_input.get(CONF_PASSWORD) or None
            errors, method = await _async_validate_web(
                self.hass,
                entry.data[CONF_HOST],
                password,
                allow_legacy=entry.data.get(CONF_WEB_AUTH) != AUTH_HMAC,
            )
            data = _with_password(entry.data, password, method)
            if not errors and _is_kiss(entry):
                errors, data = await _async_check_kiss_password(entry, user_input, data)
            if not errors:
                return self.async_update_reload_and_abort(entry, data=data)
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_password_schema(entry),
            errors=errors,
            description_placeholders={"node": entry.title},
        )


_PASSWORD_SCHEMA = vol.Schema(
    {vol.Optional(CONF_PASSWORD): TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))}
)


def _password_schema(entry: ConfigEntry) -> vol.Schema:
    """Web password, plus the KISS password for nodes reached through KISS."""
    if not _is_kiss(entry):
        return _PASSWORD_SCHEMA
    return _PASSWORD_SCHEMA.extend(
        {
            vol.Optional(CONF_KISS_PASSWORD): TextSelector(
                TextSelectorConfig(type=TextSelectorType.PASSWORD)
            )
        }
    )


def _is_kiss(entry: ConfigEntry) -> bool:
    return entry.data.get(CONF_ACCESS) == ACCESS_KISS


def _valid_kiss_password(password: str) -> bool:
    return 0 < len(password.rstrip(" ")) <= MAX_KISS_PASSWORD and password.isascii()


async def _async_validate_kiss(
    host: str, port: int, callsign: str, password: str | None
) -> dict[str, str]:
    """One login on the KISS interface (no retries)."""
    connection = KissConnection(host, callsign, password, lambda _packet: None, port=port)
    try:
        await connection.connect()
    except KissAuthRequiredError:
        return {"base": "kiss_auth_required"}
    except KissAuthError:
        return {"base": "invalid_kiss_auth"}
    except KissConnectionError:
        return {"base": "kiss_cannot_connect"}
    finally:
        await connection.close()
    return {}


async def _async_check_kiss_password(
    entry: ConfigEntry, user_input: dict[str, Any], data: dict[str, Any]
) -> tuple[dict[str, str], dict[str, Any]]:
    """Validate the KISS password of a reauth/reconfigure form."""
    password = user_input.get(CONF_KISS_PASSWORD) or None
    if password is not None and not _valid_kiss_password(password):
        return {CONF_KISS_PASSWORD: "invalid_kiss_password"}, data
    # The flow holds no connection while the entry is loaded: free the
    # node's single client slot first.
    runtime = getattr(entry, "runtime_data", None)
    if runtime is not None and runtime.kiss is not None:
        await runtime.kiss.async_stop()
    errors = await _async_validate_kiss(
        entry.data[CONF_HOST], entry.data[CONF_KISS_PORT], entry.data[CONF_CALLSIGN], password
    )
    if errors:
        if runtime is not None and runtime.kiss is not None:
            runtime.kiss.async_start()
        return errors, data
    new = {key: value for key, value in data.items() if key != CONF_KISS_PASSWORD}
    if password:
        new[CONF_KISS_PASSWORD] = password
    return {}, new


def _with_password(
    data: Mapping[str, Any], password: str | None, method: str | None
) -> dict[str, Any]:
    new = {key: value for key, value in data.items() if key != CONF_PASSWORD}
    if password:
        new[CONF_PASSWORD] = password
    if method == AUTH_HMAC:
        new[CONF_WEB_AUTH] = AUTH_HMAC
    return new


async def _async_validate_web(
    hass: HomeAssistant, host: str, password: str | None, *, allow_legacy: bool = True
) -> tuple[dict[str, str], str | None]:
    """Check the web password with one login (no retries, see F-06).

    Returns the errors and the login method the node used.
    """
    client = MeshComWebClient(
        async_get_clientsession(hass), host, password, allow_legacy=allow_legacy
    )
    try:
        await client.get_param("nomsgall")
    except WebAuthError:
        return {"base": "invalid_auth"}, None
    except WebThrottledError:
        return {"base": "throttled"}, None
    except WebDowngradeError:
        return {"base": "downgrade"}, None
    except WebApiError:
        return {"base": "cannot_connect"}, None
    return {}, client.auth_method


def _parse_groups(value: str) -> list[str] | None:
    """Comma separated group numbers, or None if one is invalid."""
    groups = [part.strip() for part in value.split(",") if part.strip()]
    if len(groups) > 20 or not all(is_group(group) for group in groups):
        return None
    return list(dict.fromkeys(groups))


class MeshComOptionsFlow(OptionsFlow):
    """Groups for the group select and users released for sending."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Show and save the options."""
        errors: dict[str, str] = {}
        if user_input is not None:
            groups = _parse_groups(user_input.get(CONF_GROUPS, ""))
            if groups is None:
                errors[CONF_GROUPS] = "invalid_groups"
            else:
                return self.async_create_entry(
                    data={
                        CONF_GROUPS: groups,
                        CONF_SEND_USERS: list(user_input.get(CONF_SEND_USERS, [])),
                        CONF_STATION_MODE: user_input[CONF_STATION_MODE],
                        CONF_STATION_MAX: int(user_input[CONF_STATION_MAX]),
                        CONF_STATION_STALE_DAYS: int(user_input[CONF_STATION_STALE_DAYS]),
                        CONF_INACTIVE_MINUTES: int(
                            user_input.get(CONF_INACTIVE_MINUTES, DEFAULT_INACTIVE_MINUTES)
                        ),
                        CONF_HIDE_FOREIGN_GROUPS: bool(
                            user_input.get(CONF_HIDE_FOREIGN_GROUPS, DEFAULT_HIDE_FOREIGN_GROUPS)
                        ),
                        CONF_RADIO_STATS: bool(
                            user_input.get(CONF_RADIO_STATS, DEFAULT_RADIO_STATS)
                        ),
                        CONF_NEIGHBOUR_LOST_HOURS: int(
                            user_input.get(CONF_NEIGHBOUR_LOST_HOURS, DEFAULT_NEIGHBOUR_LOST_HOURS)
                        ),
                    }
                )
        # Administrators may always transmit; only other users are offered.
        users = [
            SelectOptionDict(value=user.id, label=user.name or user.id)
            for user in await self.hass.auth.async_get_users()
            if user.is_active and not user.system_generated and not user.is_admin
        ]
        options = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Optional(CONF_GROUPS, default=", ".join(options.get(CONF_GROUPS, []))): str,
                vol.Optional(
                    CONF_SEND_USERS, default=options.get(CONF_SEND_USERS, [])
                ): SelectSelector(
                    SelectSelectorConfig(options=users, multiple=True, mode=SelectSelectorMode.LIST)
                ),
                vol.Required(
                    CONF_HIDE_FOREIGN_GROUPS,
                    default=options.get(CONF_HIDE_FOREIGN_GROUPS, DEFAULT_HIDE_FOREIGN_GROUPS),
                ): bool,
                vol.Required(
                    CONF_STATION_MODE, default=station_mode(self.config_entry)
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=list(STATION_MODES),
                        mode=SelectSelectorMode.LIST,
                        translation_key=CONF_STATION_MODE,
                    )
                ),
                vol.Required(
                    CONF_STATION_MAX,
                    default=options.get(CONF_STATION_MAX, DEFAULT_STATION_MAX),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=1, max=STATION_MAX_LIMIT, step=1, mode=NumberSelectorMode.BOX
                    )
                ),
                vol.Required(
                    CONF_STATION_STALE_DAYS,
                    default=options.get(CONF_STATION_STALE_DAYS, DEFAULT_STATION_STALE_DAYS),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=1, max=STATION_STALE_DAYS_LIMIT, step=1, mode=NumberSelectorMode.BOX
                    )
                ),
                vol.Required(
                    CONF_INACTIVE_MINUTES,
                    default=options.get(CONF_INACTIVE_MINUTES, DEFAULT_INACTIVE_MINUTES),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=INACTIVE_MINUTES_RANGE[0],
                        max=INACTIVE_MINUTES_RANGE[1],
                        step=1,
                        mode=NumberSelectorMode.BOX,
                        unit_of_measurement="min",
                    )
                ),
                vol.Required(
                    CONF_RADIO_STATS,
                    default=options.get(CONF_RADIO_STATS, DEFAULT_RADIO_STATS),
                ): bool,
                vol.Required(
                    CONF_NEIGHBOUR_LOST_HOURS,
                    default=options.get(CONF_NEIGHBOUR_LOST_HOURS, DEFAULT_NEIGHBOUR_LOST_HOURS),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=0,
                        max=NEIGHBOUR_LOST_HOURS_MAX,
                        step=1,
                        mode=NumberSelectorMode.BOX,
                        unit_of_measurement="h",
                    )
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)
