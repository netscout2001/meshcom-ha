"""Restored message sensors, signal of the last message, web values, node id migration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    mock_restore_cache_with_extra_data,
)

from custom_components.meshcom.const import (
    CONF_ACCESS,
    CONF_CALLSIGN,
    CONF_KISS_PORT,
    CONF_LISTEN_PORT,
    CONF_NODE_ID,
    DOMAIN,
)
from custom_components.meshcom.migration import async_migrate_entry, callsign_node_id

from .conftest import INCOMING_MESSAGE, NODE_HOST, NODE_ID, FakeWebClient, datagram, inject

PREFIX = "sensor.meshcom_do8re_12_"

STATION_POSITION = datagram(
    src_type="lora",
    type="pos",
    src="TST3-12",
    msg="",
    lat=47.6,
    lat_dir="N",
    long=12.1,
    long_dir="E",
    aprs_symbol="-",
    aprs_symbol_group="/",
    hw_id=12,
    msg_id="40000ED9",
    alt=500,
    lora_mod=8,
    max_hop=2,
    batt=70,
    firmware=40,
    fw_sub="a",
    rssi=-90,
    snr=8,
)
SERVER_MESSAGE = datagram(
    src_type="udp",
    type="msg",
    src="TST4-12",
    dst="262",
    msg="via server",
    msg_id="40000EDA",
    firmware=40,
    fw_sub="a",
    rssi=0,
    snr=0,
    hw_id=3,
    lora_mod=8,
    max_hop=4,
)


def _timestamp(value: str) -> dict[str, str]:
    return {"__type": "<class 'datetime.datetime'>", "isoformat": value}


async def test_message_sensors_survive_restart(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Last message, sender, time and signal stay; counters continue."""
    mock_restore_cache_with_extra_data(
        hass,
        [
            (
                State(f"{PREFIX}last_message", "Hallo"),
                {"native_value": "Hallo", "native_unit_of_measurement": None},
            ),
            (
                State(f"{PREFIX}last_sender", "TST9-1"),
                {"native_value": "TST9-1", "native_unit_of_measurement": None},
            ),
            (
                State(f"{PREFIX}last_message_received", "2026-11-09T11:00:00+00:00"),
                {
                    "native_value": _timestamp("2026-11-09T11:00:00+00:00"),
                    "native_unit_of_measurement": None,
                },
            ),
            (
                State(f"{PREFIX}messages_received", "41"),
                {"native_value": 41, "native_unit_of_measurement": None},
            ),
            (
                State(f"{PREFIX}messages_sent", "3"),
                {"native_value": 3, "native_unit_of_measurement": None},
            ),
        ],
    )
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(f"{PREFIX}last_message").state == "Hallo"  # type: ignore[union-attr]
    assert hass.states.get(f"{PREFIX}last_sender").state == "TST9-1"  # type: ignore[union-attr]
    assert hass.states.get(f"{PREFIX}last_message_received").state == "2026-11-09T11:00:00+00:00"  # type: ignore[union-attr]
    assert hass.states.get(f"{PREFIX}messages_received").state == "41"  # type: ignore[union-attr]
    assert hass.states.get(f"{PREFIX}messages_sent").state == "3"  # type: ignore[union-attr]

    inject(mock_config_entry, INCOMING_MESSAGE)
    await hass.async_block_till_done()
    assert hass.states.get(f"{PREFIX}last_sender").state == "TST1-12"  # type: ignore[union-attr]
    assert hass.states.get(f"{PREFIX}messages_received").state == "42"  # type: ignore[union-attr]


async def test_counter_ignores_garbage(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Only a plain non-negative number continues the counter."""
    mock_restore_cache_with_extra_data(
        hass,
        [
            (
                State(f"{PREFIX}messages_received", "x"),
                {"native_value": -5, "native_unit_of_measurement": None},
            )
        ],
    )
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry.runtime_data.node.messages_received == 0


async def test_signal_belongs_to_last_message(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Beacons of other stations do not change the signal of the last message."""
    node = init_integration.runtime_data.node
    inject(init_integration, STATION_POSITION)
    await hass.async_block_till_done()
    assert node.last_radio == (None, None)
    inject(init_integration, INCOMING_MESSAGE)
    await hass.async_block_till_done()
    assert node.last_radio == (-110, -5)
    # Via the server there is no signal: unknown, not the old value.
    inject(init_integration, SERVER_MESSAGE)
    await hass.async_block_till_done()
    assert node.last_message is not None
    assert node.last_message.sender == "TST4-12"
    assert node.last_radio[0] is None


async def test_web_firmware_and_voltage(
    hass: HomeAssistant, init_integration: MockConfigEntry, web_client: FakeWebClient
) -> None:
    """Firmware (until a packet tells it) and battery voltage come from the web page."""
    assert hass.states.get(f"{PREFIX}firmware").state == "4.40a"  # type: ignore[union-attr]
    voltage = hass.states.get(f"{PREFIX}battery_voltage")
    assert voltage is not None
    assert float(voltage.state) == 4.012
    assert voltage.attributes["unit_of_measurement"] == "V"

    web_client.battery_voltage = None  # USB, no battery
    await init_integration.runtime_data.web.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(f"{PREFIX}battery_voltage").state == "unknown"  # type: ignore[union-attr]


# --- node id migration (config entry 1.1 -> 1.2) --------------------------------

OLD_UDP_ID = 0x63CF32D3 >> 10


def _old_udp_entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="DO8RE-12",
        unique_id=f"{OLD_UDP_ID:06x}",
        minor_version=1,
        data={
            CONF_HOST: NODE_HOST,
            CONF_LISTEN_PORT: 1799,
            CONF_CALLSIGN: "DO8RE-12",
            CONF_NODE_ID: OLD_UDP_ID,
        },
    )


async def test_migrate_udp_node_id(hass: HomeAssistant) -> None:
    """Entities and devices keep their entity ids and settings under the new id."""
    entry = _old_udp_entry()
    entry.add_to_hass(hass)
    entities = er.async_get(hass)
    devices = dr.async_get(hass)
    old = f"{OLD_UDP_ID:06x}"
    node_device = devices.async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={(DOMAIN, old)}
    )
    station_device = devices.async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={(DOMAIN, f"{old}_TST1-12")}
    )
    battery = entities.async_get_or_create(
        "sensor",
        DOMAIN,
        f"{old}_battery",
        config_entry=entry,
        device_id=node_device.id,
        suggested_object_id="meshcom_do8re_12_battery",
    )
    entities.async_update_entity(battery.entity_id, name="Akku Dachboden")

    # The migration on its own: setup removes station devices in "data" mode.
    assert await async_migrate_entry(hass, entry)
    assert devices.async_get(station_device.id).identifiers == {  # type: ignore[union-attr]
        (DOMAIN, f"{NODE_ID:06x}_TST1-12")
    }

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert entry.minor_version == 2
    assert entry.data[CONF_NODE_ID] == NODE_ID
    assert entry.unique_id == f"{NODE_ID:06x}"
    migrated = entities.async_get(battery.entity_id)
    assert migrated is not None
    assert migrated.unique_id == f"{NODE_ID:06x}_battery"
    assert migrated.name == "Akku Dachboden"
    assert devices.async_get(node_device.id).identifiers == {(DOMAIN, f"{NODE_ID:06x}")}  # type: ignore[union-attr]


async def test_migrate_kiss_unique_id(hass: HomeAssistant) -> None:
    """KISS entries keep their ids; only the entry's unique id changes."""
    call = "DO8RE-9"
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=call,
        unique_id=f"kiss_{call}",
        minor_version=1,
        data={
            CONF_HOST: "192.0.2.9",
            CONF_CALLSIGN: call,
            CONF_NODE_ID: callsign_node_id(call),
            CONF_ACCESS: "kiss",
            CONF_KISS_PORT: 8001,
        },
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.minor_version == 2
    assert entry.unique_id == f"{callsign_node_id(call):06x}"


async def test_migrate_conflict_and_future_version(hass: HomeAssistant) -> None:
    """A clash or a newer version stops the migration instead of guessing."""
    entry = _old_udp_entry()
    entry.add_to_hass(hass)
    MockConfigEntry(
        domain=DOMAIN, unique_id=f"{NODE_ID:06x}", minor_version=2, data={}
    ).add_to_hass(hass)
    assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.MIGRATION_ERROR

    future = MockConfigEntry(domain=DOMAIN, version=2, data={CONF_CALLSIGN: "TST7-1"})
    future.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(future.entry_id)
    assert future.state is ConfigEntryState.MIGRATION_ERROR
