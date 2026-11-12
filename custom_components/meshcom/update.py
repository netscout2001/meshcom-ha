"""Firmware update of the node (built-in update of firmware 4.40a and later).

The node looks for new releases itself and downloads the image on request;
an automatic install is not possible in the firmware. Home Assistant shows
what the node reports and, on "Install", asks the node to download the
release and then to install it (the node restarts).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Final

from homeassistant.components.update import UpdateEntity, UpdateEntityFeature
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import MeshComConfigEntry
from .aiomeshcom.webapi import (
    AUTH_LEGACY,
    UPDATE_DOWNLOAD,
    UPDATE_INSTALL,
    WebApiError,
    WebAuthError,
    WebConnectionError,
)
from .aiomeshcom.webpages import UpdateStatus
from .const import DOMAIN
from .coordinator import MeshComWebCoordinator
from .entity import async_require_admin, node_device_info
from .node import MeshComNode

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 1

RELEASE_URL: Final = "https://github.com/icssw-org/MeshCom-Firmware/releases/tag/{tag}"
#: How often the node is asked while it downloads, and for how long.
DOWNLOAD_POLL: Final = 5.0
DOWNLOAD_TIMEOUT: Final = 15 * 60.0
#: How often the node is asked after the install request, and for how long.
RESTART_POLL: Final = 10.0
RESTART_TIMEOUT: Final = 10 * 60.0
#: Answers with the old firmware after the restart until the install counts
#: as failed (the Safeboot fallback keeps the old image).
OLD_VERSION_ANSWERS: Final = 3


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MeshComConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the update entity once the node reports a built-in update."""
    runtime = entry.runtime_data
    web = runtime.web

    def _supported() -> bool:
        return web.data is not None and web.data.update is not None

    if _supported():
        async_add_entities([MeshComFirmwareUpdate(web, runtime.node)])
        return

    remove_listener: list[Any] = []

    @callback
    def _check() -> None:
        if _supported() and remove_listener:
            remove_listener.pop()()
            async_add_entities([MeshComFirmwareUpdate(web, runtime.node)])

    remove_listener.append(web.async_add_listener(_check))

    @callback
    def _cleanup() -> None:
        if remove_listener:
            remove_listener.pop()()

    entry.async_on_unload(_cleanup)


class MeshComFirmwareUpdate(CoordinatorEntity[MeshComWebCoordinator], UpdateEntity):
    """Firmware of the own node."""

    _attr_has_entity_name = True
    _attr_translation_key = "firmware"

    def __init__(self, coordinator: MeshComWebCoordinator, node: MeshComNode) -> None:
        super().__init__(coordinator)
        self.node = node
        self._attr_unique_id = f"{node.node_id:06x}_firmware"
        self._attr_device_info = node_device_info(node)
        self._installing = False
        self._progress: int | None = None

    @property
    def _status(self) -> UpdateStatus | None:
        data = self.coordinator.data
        return data.update if data is not None else None

    @property
    def available(self) -> bool:
        """Available while the node answers and reports its update state."""
        return super().available and self._status is not None

    @property
    def supported_features(self) -> UpdateEntityFeature:
        """Install only on boards that can (Safeboot) and with an image for them."""
        status = self._status
        if status is not None and status.safeboot_ok and status.installable:
            return UpdateEntityFeature.INSTALL | UpdateEntityFeature.PROGRESS
        return UpdateEntityFeature(0)

    @property
    def installed_version(self) -> str | None:
        """Tag of the running firmware."""
        status = self._status
        return status.running if status is not None else None

    @property
    def latest_version(self) -> str | None:
        """The release the node found, if it rates it as newer."""
        status = self._status
        if status is None:
            return None
        if status.newer and status.available is not None:
            return status.available
        return status.running

    def version_is_newer(self, latest_version: str, installed_version: str) -> bool:
        """The node decides what is newer (tags like v4.40a.11.07)."""
        return latest_version != installed_version

    @property
    def release_url(self) -> str | None:
        """Release page of the newer firmware."""
        latest = self.latest_version
        if latest is None or latest == self.installed_version:
            return None
        return RELEASE_URL.format(tag=latest)

    @property
    def in_progress(self) -> bool:
        """True while Home Assistant installs or the node downloads."""
        status = self._status
        return self._installing or (
            status is not None and status.state == "busy" and status.job == "download"
        )

    @property
    def update_percentage(self) -> int | None:
        """Download progress."""
        if self._progress is not None:
            return self._progress
        status = self._status
        if status is not None and status.state == "busy" and status.job == "download":
            return status.percent
        return None

    async def async_install(self, version: str | None, backup: bool, **kwargs: Any) -> None:
        """Let the node download the release, then install it (it restarts)."""
        await async_require_admin(self.hass, self._context, self.node.entry_id)
        status = self._status
        target = self.latest_version
        if (
            status is None
            or target is None
            or target == status.running
            or (version is not None and version != target)
            or not (status.safeboot_ok and status.installable)
        ):
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="update_not_possible"
            )
        if self.coordinator.client.auth_method == AUTH_LEGACY:
            # The plain-text login would send the password every few seconds
            # while the update runs.
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="update_needs_secure_login"
            )
        self._installing = True
        self._progress = 0
        self.async_write_ha_state()
        try:
            await self._async_run(target, status)
        except WebAuthError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="web_auth_failed"
            ) from err
        except WebApiError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="web_unavailable"
            ) from err
        finally:
            self._installing = False
            self._progress = None
            self.async_write_ha_state()
            await self.coordinator.async_request_refresh()

    async def _async_run(self, target: str, status: UpdateStatus) -> None:
        client = self.coordinator.client
        _LOGGER.info("%s: firmware update to %s requested", self.node.callsign, target)
        if status.staged != target:
            if not await client.update_action(UPDATE_DOWNLOAD):
                current = await client.get_update_status()
                raise _failed("update_rejected", current.error if current else None)
            await self._async_wait_download(target)
        self._progress = 100
        self.async_write_ha_state()
        if not await client.update_action(UPDATE_INSTALL):
            raise _failed("update_rejected", None)
        await self._async_wait_restart(target)
        _LOGGER.info("%s: firmware %s installed", self.node.callsign, target)

    async def _async_wait_download(self, target: str) -> None:
        client = self.coordinator.client
        loop = asyncio.get_running_loop()
        deadline = loop.time() + DOWNLOAD_TIMEOUT
        while loop.time() < deadline:
            await asyncio.sleep(DOWNLOAD_POLL)
            try:
                current = await client.get_update_status()
            except WebConnectionError:
                continue  # the node is busy downloading
            if current is None:
                continue
            if current.state == "busy":
                self._progress = current.percent
                self.async_write_ha_state()
                continue
            if current.staged == target:
                return
            # The download job ended without the image (the node answers
            # "busy" from the moment it accepted the request).
            raise _failed("update_failed", current.error)
        raise HomeAssistantError(translation_domain=DOMAIN, translation_key="update_timeout")

    async def _async_wait_restart(self, target: str) -> None:
        client = self.coordinator.client
        loop = asyncio.get_running_loop()
        deadline = loop.time() + RESTART_TIMEOUT
        restarted = False
        old_answers = 0
        while loop.time() < deadline:
            await asyncio.sleep(RESTART_POLL)
            try:
                current = await client.get_update_status()
            except WebConnectionError:
                restarted = True  # unreachable while it installs and restarts
                continue
            if current is None:
                continue
            if current.running == target:
                return
            if restarted:
                old_answers += 1
                if old_answers >= OLD_VERSION_ANSWERS:
                    raise HomeAssistantError(
                        translation_domain=DOMAIN, translation_key="update_install_failed"
                    )
        raise HomeAssistantError(translation_domain=DOMAIN, translation_key="update_timeout")


def _failed(key: str, error: str | None) -> HomeAssistantError:
    """A translated error; a connected phone gets its own hint."""
    if error is not None and error.startswith("lowheap_phone"):
        return HomeAssistantError(translation_domain=DOMAIN, translation_key="update_phone")
    return HomeAssistantError(
        translation_domain=DOMAIN,
        translation_key=key,
        translation_placeholders={"error": error or "-"},
    )
