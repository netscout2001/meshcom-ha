"""Service actions of MeshCom."""

from __future__ import annotations

from typing import TYPE_CHECKING

import voluptuous as vol
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import ATTR_CONFIG_ENTRY_ID
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .const import ATTR_DESTINATION, ATTR_MESSAGE, DOMAIN, SERVICE_SEND_MESSAGE
from .sender import async_send_text

if TYPE_CHECKING:
    from . import MeshComConfigEntry

SEND_MESSAGE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Required(ATTR_DESTINATION): vol.All(cv.string, vol.Length(min=1, max=9)),
        vol.Required(ATTR_MESSAGE): vol.All(cv.string, vol.Length(min=1, max=150)),
    }
)


def _loaded_entry(hass: HomeAssistant, entry_id: str) -> MeshComConfigEntry:
    entry = hass.config_entries.async_get_entry(entry_id)
    if entry is None or entry.domain != DOMAIN:
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="entry_not_found")
    if entry.state is not ConfigEntryState.LOADED:
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="entry_not_loaded")
    return entry


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the service actions."""

    async def _send_message(call: ServiceCall) -> None:
        entry = _loaded_entry(hass, call.data[ATTR_CONFIG_ENTRY_ID])
        await async_send_text(
            hass, entry, call.data[ATTR_DESTINATION], call.data[ATTR_MESSAGE], call.context
        )

    hass.services.async_register(
        DOMAIN, SERVICE_SEND_MESSAGE, _send_message, schema=SEND_MESSAGE_SCHEMA
    )
