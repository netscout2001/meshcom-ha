"""Tests for setup, entities, events and diagnostics."""

from __future__ import annotations

from unittest.mock import patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
    mock_restore_cache,
)
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
)
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from custom_components.meshcom.const import EVENT_DELIVERY, EVENT_MESSAGE
from custom_components.meshcom.hub import UdpHub

from .conftest import (
    ACK_TEXT,
    INCOMING_MESSAGE,
    OWN_MESSAGE,
    OWN_POSITION,
    OWN_TELEMETRY,
    OWN_TELEMETRY_EMPTY,
    inject,
)

BATTERY = "sensor.meshcom_do8re_12_battery"
TRACKER = "device_tracker.meshcom_do8re_12_position"
ACTIVE = "binary_sensor.meshcom_do8re_12_active"
LAST_MESSAGE = "sensor.meshcom_do8re_12_last_message"
LAST_SENDER = "sensor.meshcom_do8re_12_last_sender"
RECEIVED = "sensor.meshcom_do8re_12_messages_received"
SENT = "sensor.meshcom_do8re_12_messages_sent"
FIRMWARE = "sensor.meshcom_do8re_12_firmware"
TEMPERATURE = "sensor.meshcom_do8re_12_temperature_1"


async def test_setup_and_unload(hass: HomeAssistant, init_integration: MockConfigEntry) -> None:
    """Setup opens the hub, unload closes it."""
    assert init_integration.state is ConfigEntryState.LOADED
    assert 1799 in hass.data["meshcom_hubs"]
    assert hass.states.get(ACTIVE).state == "off"  # type: ignore[union-attr]

    await hass.config_entries.async_unload(init_integration.entry_id)
    await hass.async_block_till_done()
    assert init_integration.state is ConfigEntryState.NOT_LOADED  # type: ignore[comparison-overlap]
    assert 1799 not in hass.data["meshcom_hubs"]


async def test_port_unavailable(hass: HomeAssistant, mock_config_entry: MockConfigEntry) -> None:
    """A blocked port makes the entry retry later."""
    mock_config_entry.add_to_hass(hass)
    with patch.object(UdpHub, "async_start", side_effect=OSError):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_own_position(hass: HomeAssistant, init_integration: MockConfigEntry) -> None:
    """The own beacon updates battery, firmware, tracker and activity."""
    inject(init_integration, OWN_POSITION)
    await hass.async_block_till_done()
    assert hass.states.get(BATTERY).state == "96"  # type: ignore[union-attr]
    assert hass.states.get(FIRMWARE).state == "4.40a"  # type: ignore[union-attr]
    tracker = hass.states.get(TRACKER)
    assert tracker is not None
    assert tracker.attributes["latitude"] == 47.5
    assert tracker.attributes["longitude"] == 12.0
    assert hass.states.get(ACTIVE).state == "on"  # type: ignore[union-attr]


async def test_own_position_restored(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """After a restart the last position stays until the next own beacon."""
    mock_restore_cache(hass, [State(TRACKER, "not_home", {"latitude": 47.1, "longitude": 11.9})])
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    tracker = hass.states.get(TRACKER)
    assert tracker is not None
    assert tracker.attributes["latitude"] == 47.1
    assert tracker.attributes["longitude"] == 11.9
    inject(mock_config_entry, OWN_POSITION)
    await hass.async_block_till_done()
    tracker = hass.states.get(TRACKER)
    assert tracker is not None
    assert tracker.attributes["latitude"] == 47.5


async def test_own_position_restore_rejects_garbage(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Only plain numbers in range are restored."""
    mock_restore_cache(hass, [State(TRACKER, "not_home", {"latitude": "47", "longitude": 200.0})])
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    tracker = hass.states.get(TRACKER)
    assert tracker is not None
    assert tracker.state == "unknown"


async def test_unknown_sender_is_dropped(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Packets from other addresses never reach the node (C-05)."""
    inject(init_integration, OWN_POSITION, host="192.168.1.66")
    await hass.async_block_till_done()
    assert hass.states.get(BATTERY).state == "unknown"  # type: ignore[union-attr]
    assert init_integration.runtime_data.hub.dropped["unknown_sender"] == 1


async def test_invalid_packet_is_counted(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Broken datagrams are dropped and counted, not logged with content."""
    inject(init_integration, b'{"type": "msg", "rssi": NaN}')
    assert init_integration.runtime_data.hub.dropped["json_constant"] == 1


async def test_rate_limit(hass: HomeAssistant, init_integration: MockConfigEntry) -> None:
    """A flood from the node address is throttled (C-10)."""
    for _ in range(200):
        inject(init_integration, b"{}")
    dropped = init_integration.runtime_data.hub.dropped
    assert dropped["rate_limit"] > 0
    assert dropped["unknown_type"] <= 61


async def test_messages_and_events(hass: HomeAssistant, init_integration: MockConfigEntry) -> None:
    """Incoming messages update sensors and fire events; text stays plain data."""
    events = async_capture_events(hass, EVENT_MESSAGE)

    inject(init_integration, INCOMING_MESSAGE)
    inject(init_integration, INCOMING_MESSAGE)  # duplicate
    inject(init_integration, OWN_MESSAGE)
    await hass.async_block_till_done()

    assert hass.states.get(LAST_MESSAGE).state == "Hallo <b>Welt</b>"  # type: ignore[union-attr]
    assert hass.states.get(LAST_SENDER).state == "TST1-12"  # type: ignore[union-attr]
    assert hass.states.get(RECEIVED).state == "1"  # type: ignore[union-attr]
    assert hass.states.get(SENT).state == "1"  # type: ignore[union-attr]

    assert len(events) == 2
    incoming, own = (event.data for event in events)
    assert incoming["destination_kind"] == "group"
    assert incoming["path"] == ["TST2-12"]
    assert incoming["is_own"] is False
    assert own["is_own"] is True
    assert own["sequence"] == 724
    assert init_integration.runtime_data.node.duplicates == 1


async def test_ack_event(hass: HomeAssistant, init_integration: MockConfigEntry) -> None:
    """A text acknowledgement addressed to this node fires a delivery event."""
    events = async_capture_events(hass, EVENT_DELIVERY)
    # Without an open own message the acknowledgement counts for nothing (C-13).
    inject(init_integration, ACK_TEXT)
    await hass.async_block_till_done()
    assert events == []

    inject(init_integration, OWN_MESSAGE)
    inject(init_integration, ACK_TEXT.replace(b"43758258", b"43758259"))
    await hass.async_block_till_done()
    assert len(events) == 1
    assert events[0].data["from"] == "DO8RE-9"
    assert events[0].data["sequence"] == 724
    assert events[0].data["msg_id"] == "63CF32D4"
    assert events[0].data["status"] == "delivered"


async def test_telemetry_entities_only_with_sensor_data(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Sensor entities appear only once the node reports real values."""
    inject(init_integration, OWN_TELEMETRY_EMPTY)
    await hass.async_block_till_done()
    assert hass.states.get(TEMPERATURE) is None

    inject(init_integration, OWN_TELEMETRY)
    await hass.async_block_till_done()
    assert hass.states.get(TEMPERATURE).state == "21.5"  # type: ignore[union-attr]


async def test_disabled_by_default(
    hass: HomeAssistant, init_integration: MockConfigEntry, entity_registry: er.EntityRegistry
) -> None:
    """Noisy diagnostics are disabled by default."""
    entry = entity_registry.async_get("sensor.meshcom_do8re_12_last_rssi")
    assert entry is not None
    assert entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION


async def test_stations_heard(hass: HomeAssistant, init_integration: MockConfigEntry) -> None:
    """Heard stations are kept as data and counted."""
    inject(init_integration, INCOMING_MESSAGE)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.meshcom_do8re_12_stations_heard_24_h").state == "1"  # type: ignore[union-attr]


async def test_diagnostics_redacted(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    init_integration: MockConfigEntry,
) -> None:
    """Diagnostics contain no address, positions or message text (C-04, C-12)."""
    inject(init_integration, OWN_POSITION)
    inject(init_integration, INCOMING_MESSAGE)
    await hass.async_block_till_done()
    diagnostics = await get_diagnostics_for_config_entry(hass, hass_client, init_integration)
    text = str(diagnostics)
    assert "192.168.1.50" not in text
    assert "47.5" not in text
    assert "Hallo" not in text
    assert "TST1-12" not in text
    assert diagnostics["entry"]["host"] == "**REDACTED**"
    assert diagnostics["node"]["messages_received"] == 1
