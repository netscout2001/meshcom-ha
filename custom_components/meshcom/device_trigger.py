"""Device triggers of the own node (messages, deliveries, stations).

Each trigger is an event trigger on one of the integration's events,
limited to the node's config entry. The event data is available in the
automation as ``trigger.event.data``.
"""

from __future__ import annotations

from typing import Any, Final

import voluptuous as vol
from homeassistant.components.device_automation import DEVICE_TRIGGER_BASE_SCHEMA
from homeassistant.components.device_automation.exceptions import InvalidDeviceAutomationConfig
from homeassistant.components.homeassistant.triggers import event as event_trigger
from homeassistant.const import (
    CONF_DEVICE_ID,
    CONF_DOMAIN,
    CONF_EVENT_DATA,
    CONF_PLATFORM,
    CONF_TYPE,
)
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.trigger import TriggerActionType, TriggerInfo
from homeassistant.helpers.typing import ConfigType

from .const import (
    DOMAIN,
    EVENT_DELIVERY,
    EVENT_MESSAGE,
    EVENT_NEIGHBOUR_BACK,
    EVENT_NEIGHBOUR_LOST,
    EVENT_STATION_NEW,
)

#: Trigger type -> (event, event data filters). Several filters: any matches.
TRIGGERS: Final[dict[str, tuple[str, tuple[dict[str, Any], ...]]]] = {
    "message_received": (EVENT_MESSAGE, ({"to_me": True},)),
    "direct_message_received": (
        EVENT_MESSAGE,
        ({"to_me": True, "destination_kind": "direct"},),
    ),
    "group_message_received": (
        EVENT_MESSAGE,
        ({"to_me": True, "destination_kind": "group"},),
    ),
    "message_delivered": (EVENT_DELIVERY, ({"status": "delivered"},)),
    "delivery_failed": (EVENT_DELIVERY, ({"status": "failed"}, {"status": "rejected"})),
    "station_new": (EVENT_STATION_NEW, ({},)),
    "neighbour_lost": (EVENT_NEIGHBOUR_LOST, ({},)),
    "neighbour_back": (EVENT_NEIGHBOUR_BACK, ({},)),
}

TRIGGER_SCHEMA = DEVICE_TRIGGER_BASE_SCHEMA.extend({vol.Required(CONF_TYPE): vol.In(TRIGGERS)})


def _node_entry_id(hass: HomeAssistant, device_id: str) -> str | None:
    """Config entry of the own node's device; None for any other device.

    Station devices belong to the same entry but are not the node: their
    identifier carries the station's callsign after the node id.
    """
    device = dr.async_get(hass).async_get(device_id)
    if device is None:
        return None
    for domain, identifier in device.identifiers:
        if domain != DOMAIN or "_" in identifier:
            continue
        for entry_id in device.config_entries:
            entry = hass.config_entries.async_get_entry(entry_id)
            if entry is not None and entry.domain == DOMAIN:
                return entry_id
    return None


async def async_validate_trigger_config(hass: HomeAssistant, config: ConfigType) -> ConfigType:
    """Validate the trigger and that the device is a MeshCom node."""
    config = TRIGGER_SCHEMA(config)
    if _node_entry_id(hass, config[CONF_DEVICE_ID]) is None:
        raise InvalidDeviceAutomationConfig(f"not a MeshCom node: {config[CONF_DEVICE_ID]}")
    return config


async def async_get_triggers(hass: HomeAssistant, device_id: str) -> list[dict[str, Any]]:
    """Triggers offered for the own node's device (none for station devices)."""
    if _node_entry_id(hass, device_id) is None:
        return []
    return [
        {
            CONF_PLATFORM: "device",
            CONF_DOMAIN: DOMAIN,
            CONF_DEVICE_ID: device_id,
            CONF_TYPE: trigger_type,
        }
        for trigger_type in TRIGGERS
    ]


async def async_attach_trigger(
    hass: HomeAssistant,
    config: ConfigType,
    action: TriggerActionType,
    trigger_info: TriggerInfo,
) -> CALLBACK_TYPE:
    """Attach one event trigger per filter of the trigger type."""
    entry_id = _node_entry_id(hass, config[CONF_DEVICE_ID])
    if entry_id is None:
        raise InvalidDeviceAutomationConfig(f"not a MeshCom node: {config[CONF_DEVICE_ID]}")
    event_type, filters = TRIGGERS[config[CONF_TYPE]]
    removers = []
    for data in filters:
        event_config = event_trigger.TRIGGER_SCHEMA(
            {
                CONF_PLATFORM: "event",
                event_trigger.CONF_EVENT_TYPE: event_type,
                CONF_EVENT_DATA: {"entry_id": entry_id, **data},
            }
        )
        removers.append(
            await event_trigger.async_attach_trigger(
                hass, event_config, action, trigger_info, platform_type="device"
            )
        )

    @callback
    def _remove() -> None:
        for remove in removers:
            remove()

    return _remove
