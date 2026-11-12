"""Device triggers of the own node."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from homeassistant.components.device_automation import DeviceAutomationType
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_get_device_automations,
)

from custom_components.meshcom import device_trigger
from custom_components.meshcom.const import (
    DOMAIN,
    EVENT_DELIVERY,
    EVENT_MESSAGE,
    EVENT_NEIGHBOUR_LOST,
)
from custom_components.meshcom.stations import station_identifier

from .conftest import NODE_ID

ALL_TYPES = {
    "message_received",
    "direct_message_received",
    "group_message_received",
    "message_delivered",
    "delivery_failed",
    "station_new",
    "neighbour_lost",
    "neighbour_back",
}


def _node_device(hass: HomeAssistant) -> dr.DeviceEntry:
    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, f"{NODE_ID:06x}")})
    assert device is not None
    return device


async def _automation(hass: HomeAssistant, device_id: str, trigger_type: str) -> None:
    assert await async_setup_component(
        hass,
        "automation",
        {
            "automation": [
                {
                    "trigger": {
                        "platform": "device",
                        "domain": DOMAIN,
                        "device_id": device_id,
                        "type": trigger_type,
                    },
                    "action": {
                        "service": "test.automation",
                        "data_template": {"callsign": "{{ trigger.event.data.callsign }}"},
                    },
                }
            ]
        },
    )


async def test_get_triggers(hass: HomeAssistant, init_integration: MockConfigEntry) -> None:
    """All types on the node's device, none on a station device."""
    device = _node_device(hass)
    triggers = await async_get_device_automations(hass, DeviceAutomationType.TRIGGER, device.id)
    own = {trigger["type"] for trigger in triggers if trigger["domain"] == DOMAIN}
    assert own == ALL_TYPES
    station = dr.async_get(hass).async_get_or_create(
        config_entry_id=init_integration.entry_id,
        identifiers={station_identifier(NODE_ID, "QR1ABC-12")},
    )
    assert await device_trigger.async_get_triggers(hass, station.id) == []
    assert await device_trigger.async_get_triggers(hass, "unknown") == []


async def test_message_triggers(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    service_calls: list[ServiceCall],
) -> None:
    """Direct messages to the node trigger; other entries and kinds do not."""
    device = _node_device(hass)
    await _automation(hass, device.id, "direct_message_received")
    base: dict[str, Any] = {"entry_id": init_integration.entry_id, "to_me": True}
    hass.bus.async_fire(EVENT_MESSAGE, {**base, "destination_kind": "group"})
    hass.bus.async_fire(EVENT_MESSAGE, {**base, "entry_id": "other", "destination_kind": "direct"})
    hass.bus.async_fire(EVENT_MESSAGE, {**base, "to_me": False, "destination_kind": "direct"})
    hass.bus.async_fire(
        EVENT_MESSAGE, {**base, "destination_kind": "direct", "callsign": "QR1ABC-12"}
    )
    await hass.async_block_till_done()
    assert [call.data["callsign"] for call in service_calls] == ["QR1ABC-12"]


@pytest.mark.parametrize("status", ["failed", "rejected"])
async def test_delivery_failed(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    service_calls: list[ServiceCall],
    status: str,
) -> None:
    """Both failure statuses trigger "not delivered"; "delivered" does not."""
    await _automation(hass, _node_device(hass).id, "delivery_failed")
    hass.bus.async_fire(
        EVENT_DELIVERY, {"entry_id": init_integration.entry_id, "status": "delivered"}
    )
    hass.bus.async_fire(
        EVENT_DELIVERY,
        {"entry_id": init_integration.entry_id, "status": status, "callsign": "x"},
    )
    await hass.async_block_till_done()
    assert len(service_calls) == 1


async def test_neighbour_trigger(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    service_calls: list[ServiceCall],
) -> None:
    """The neighbour events carry the callsign."""
    await _automation(hass, _node_device(hass).id, "neighbour_lost")
    hass.bus.async_fire(
        EVENT_NEIGHBOUR_LOST, {"entry_id": init_integration.entry_id, "callsign": "QR1ABC-12"}
    )
    await hass.async_block_till_done()
    assert [call.data["callsign"] for call in service_calls] == ["QR1ABC-12"]


async def test_invalid_device(hass: HomeAssistant, init_integration: MockConfigEntry) -> None:
    """A device that is not a MeshCom node is refused."""
    config = {"platform": "device", "domain": DOMAIN, "device_id": "nope", "type": "station_new"}
    with pytest.raises(HomeAssistantError):
        await device_trigger.async_validate_trigger_config(hass, config)
    with pytest.raises(HomeAssistantError):
        await device_trigger.async_attach_trigger(
            hass,
            device_trigger.TRIGGER_SCHEMA(config),
            MagicMock(),
            MagicMock(),
        )
    device = _node_device(hass)
    valid = await device_trigger.async_validate_trigger_config(
        hass, {**config, "device_id": device.id}
    )
    assert valid["type"] == "station_new"


async def test_detach(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    service_calls: list[ServiceCall],
) -> None:
    """Turning the automation off removes every attached event trigger."""
    await _automation(hass, _node_device(hass).id, "delivery_failed")
    await hass.services.async_call(
        "automation", "turn_off", {"entity_id": "automation.automation_0"}, blocking=True
    )
    hass.bus.async_fire(EVENT_DELIVERY, {"entry_id": init_integration.entry_id, "status": "failed"})
    await hass.async_block_till_done()
    assert [call for call in service_calls if call.domain == "test"] == []
