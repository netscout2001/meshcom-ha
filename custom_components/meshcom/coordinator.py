"""Polling of the node web API (settings that UDP does not carry)."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import timedelta
from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .aiomeshcom.webapi import (
    MeshComWebClient,
    MHeardEntry,
    WebApiError,
    WebAuthError,
    WebDowngradeError,
    WebThrottledError,
)
from .const import DOMAIN, ISSUE_WEB_DOWNGRADE

if TYPE_CHECKING:
    from . import MeshComConfigEntry

_LOGGER = logging.getLogger(__name__)

#: The node runs a single-threaded web server that shares the SPI bus with
#: the radio; poll rarely (security concept C-20).
WEB_POLL_INTERVAL = timedelta(minutes=5)


@dataclass(frozen=True, slots=True)
class WebData:
    """Settings read from the node."""

    no_msg_all: bool
    groups: list[str]
    #: From the node's info page; None if unknown.
    firmware: str | None = None
    battery_voltage: float | None = None
    #: Stations heard directly (MHeard page); None if unreadable.
    mheard: list[MHeardEntry] | None = None


class MeshComWebCoordinator(DataUpdateCoordinator[WebData]):
    """Reads the node settings with one login per poll."""

    config_entry: MeshComConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: MeshComConfigEntry,
        client: MeshComWebClient,
        node_away: Callable[[], bool] = lambda: False,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} web {entry.title}",
            update_interval=WEB_POLL_INTERVAL,
            config_entry=entry,
        )
        self.client = client
        self._node_away = node_away
        #: True while polling pauses because the node is away.
        self.paused = False
        self._force = False

    async def async_refresh_now(self) -> None:
        """Poll regardless of the node's activity (first contact at startup)."""
        self.paused = False
        self._force = True
        try:
            await self.async_refresh()
        finally:
            self._force = False

    async def _async_update_data(self) -> WebData:
        # No login attempts at an address whose node has gone quiet: the
        # address may now belong to another device, and every attempt would
        # hand it the login (the plain-text password on firmware 4.40a).
        if not self._force and self._node_away():
            self.paused = True
            raise UpdateFailed(translation_domain=DOMAIN, translation_key="web_node_away")
        self.paused = False
        try:
            status = await self.client.get_overview()
        except WebAuthError as err:
            # Starts the reauthentication flow. No retry loop: five failed
            # logins would block the node's login for everyone (F-06).
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN, translation_key="web_auth_failed"
            ) from err
        except WebThrottledError as err:
            raise UpdateFailed(translation_domain=DOMAIN, translation_key="web_throttled") from err
        except WebDowngradeError as err:
            # The node used the secure login before and now offers only the
            # plain-text one: firmware downgrade or someone impersonating it.
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                self._downgrade_issue_id,
                is_fixable=False,
                severity=ir.IssueSeverity.ERROR,
                translation_key=ISSUE_WEB_DOWNGRADE,
                translation_placeholders={"node": self.config_entry.title},
            )
            raise UpdateFailed(translation_domain=DOMAIN, translation_key="web_downgrade") from err
        except WebApiError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN, translation_key="web_unavailable"
            ) from err
        ir.async_delete_issue(self.hass, DOMAIN, self._downgrade_issue_id)
        return WebData(
            no_msg_all=status.no_msg_all,
            groups=status.groups,
            firmware=status.firmware,
            battery_voltage=status.battery_voltage,
            mheard=status.mheard,
        )

    @property
    def _downgrade_issue_id(self) -> str:
        return f"{ISSUE_WEB_DOWNGRADE}_{self.config_entry.entry_id}"

    async def async_set_no_msg_all(self, enabled: bool) -> None:
        """Switch "No MSG All" on the node and take over the node's answer."""
        try:
            value = await self.client.set_param("nomsgall", "on" if enabled else "off")
        except WebAuthError as err:
            self.config_entry.async_start_reauth(self.hass)
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="web_auth_failed"
            ) from err
        except WebDowngradeError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="web_downgrade"
            ) from err
        except WebApiError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="web_unavailable"
            ) from err
        if self.data is not None:
            self.async_set_updated_data(replace(self.data, no_msg_all=value == "on"))
        else:
            await self.async_request_refresh()
