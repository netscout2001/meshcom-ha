"""Config entry migrations and the node id."""

from __future__ import annotations

import logging
import zlib

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .const import CONF_CALLSIGN, CONF_NODE_ID, DOMAIN

_LOGGER = logging.getLogger(__name__)


def callsign_node_id(callsign: str) -> int:
    """The stable 22-bit id of a node, derived from its callsign.

    Used for both access paths: KISS frames carry no MeshCom message id, and
    one id for both keeps a node's device and entities when it is moved from
    KISS to UDP or back.
    """
    return zlib.crc32(callsign.encode()) & 0x3FFFFF


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate an entry to the current version."""
    if entry.version > 1:
        # Downgrade from a future version.
        return False
    if entry.minor_version < 2:
        return _migrate_node_id(hass, entry)
    return True


def _migrate_node_id(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """1.1 -> 1.2: node id from the callsign for UDP and KISS alike.

    UDP nodes used the hardware part of their message ids, KISS nodes a
    checksum of the callsign. Entities, devices and the entry's unique id
    are renamed in place, so entity ids, history and settings stay.
    """
    callsign = entry.data[CONF_CALLSIGN]
    old = int(entry.data[CONF_NODE_ID])
    new = callsign_node_id(callsign)
    new_unique_id = f"{new:06x}"
    for other in hass.config_entries.async_entries(DOMAIN):
        if other.entry_id != entry.entry_id and other.unique_id == new_unique_id:
            _LOGGER.error("MeshCom node %s: another entry already uses its id", callsign)
            return False
    if old != new:
        old_prefix, new_prefix = f"{old:06x}", new_unique_id
        entities = er.async_get(hass)
        for item in er.async_entries_for_config_entry(entities, entry.entry_id):
            if item.unique_id.startswith(f"{old_prefix}_"):
                entities.async_update_entity(
                    item.entity_id, new_unique_id=new_prefix + item.unique_id[len(old_prefix) :]
                )
        devices = dr.async_get(hass)
        for device in dr.async_entries_for_config_entry(devices, entry.entry_id):
            identifiers = {
                (domain, new_prefix + value[len(old_prefix) :])
                if domain == DOMAIN and (value == old_prefix or value.startswith(f"{old_prefix}_"))
                else (domain, value)
                for domain, value in device.identifiers
            }
            if identifiers != device.identifiers:
                devices.async_update_device(device.id, new_identifiers=identifiers)
    hass.config_entries.async_update_entry(
        entry,
        data={**entry.data, CONF_NODE_ID: new},
        unique_id=new_unique_id,
        minor_version=2,
    )
    _LOGGER.debug("MeshCom node %s migrated to node id %s", callsign, new_unique_id)
    return True
