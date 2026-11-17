"""Entities of remote-managed nodes (one device per node, issue #50).

States come only from verified answers. Before the first answer, or after
a command without answer, values are unknown rather than guessed.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING, Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.components.button import ButtonDeviceClass, ButtonEntity
from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.components.select import SelectEntity
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.components.switch import SwitchEntity
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .aiomeshcom.rm import LED_MODES, TOGGLES
from .const import DOMAIN, signal_remote
from .entity import async_require_admin

if TYPE_CHECKING:
    from . import MeshComConfigEntry
    from .remote import RemoteManager, RemoteNode

#: Range used until the node reported its own (status "p=cur/min/max").
DEFAULT_TX_RANGE = (0, 30)


def remote_device_info(own_node_id: int, callsign: str, version: str | None) -> DeviceInfo:
    """Device of a remote-managed node, linked to the own node."""
    return DeviceInfo(
        identifiers={(DOMAIN, f"{own_node_id:06x}_rm_{callsign}")},
        name=f"MeshCom {callsign} (RM)",
        manufacturer="MeshCom",
        model="Remote-managed node",
        sw_version=version,
        via_device=(DOMAIN, f"{own_node_id:06x}"),
    )


class RemoteEntity(Entity):
    """Base of all entities of one remote node."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, entry: MeshComConfigEntry, remote: RemoteNode, key: str) -> None:
        self._entry = entry
        self.remote = remote
        node_id = entry.runtime_data.node.node_id
        self._attr_unique_id = f"{node_id:06x}_rm_{remote.callsign}_{key}"
        self._attr_translation_key = f"rm_{key}"
        self._attr_device_info = remote_device_info(
            node_id, remote.callsign, remote.status.version if remote.status else None
        )

    @property
    def manager(self) -> RemoteManager:
        """The manager of the own node."""
        return self._entry.runtime_data.remote

    async def async_added_to_hass(self) -> None:
        """Follow the remote node's state."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                signal_remote(self._entry.entry_id, self.remote.subentry_id),
                self._handle_update,
            )
        )

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()

    async def _run(self, cmd: str, args: str = "") -> str:
        # Remote management is for administrators only (automations run as the owner).
        await async_require_admin(self.hass, self._context, self._entry.entry_id)
        return await self.manager.async_command(self.remote.subentry_id, cmd, args, self._context)


class RemoteButton(RemoteEntity, ButtonEntity):
    """Read the status, send position/track, or restart the node."""

    def __init__(self, entry: MeshComConfigEntry, remote: RemoteNode, cmd: str) -> None:
        super().__init__(entry, remote, cmd)
        self._cmd = cmd
        if cmd == "reboot":
            self._attr_device_class = ButtonDeviceClass.RESTART
            self._attr_entity_category = EntityCategory.CONFIG

    async def async_press(self) -> None:
        """Send the command and wait for the answer."""
        await self._run(self._cmd)


class RemoteSwitch(RemoteEntity, SwitchEntity):
    """One of the node's switches (GPS, track, display, gateway, mesh)."""

    def __init__(self, entry: MeshComConfigEntry, remote: RemoteNode, name: str) -> None:
        super().__init__(entry, remote, name)
        self._name = name
        if name in ("gateway", "mesh", "display"):
            self._attr_entity_category = EntityCategory.CONFIG

    @property
    def is_on(self) -> bool | None:
        """As last confirmed by the node; None while unknown."""
        return self.remote.switches.get(self._name)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Switch on through remote management."""
        await self._run(self._name, "on")

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Switch off through remote management."""
        await self._run(self._name, "off")


class RemoteTxPower(RemoteEntity, NumberEntity):
    """Transmit power of the chip in dBm (the node checks the range itself)."""

    _attr_mode = NumberMode.BOX
    _attr_native_step = 1
    _attr_native_unit_of_measurement = "dBm"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, entry: MeshComConfigEntry, remote: RemoteNode) -> None:
        super().__init__(entry, remote, "txpower")

    @property
    def native_value(self) -> int | None:
        """As last confirmed by the node."""
        return self.remote.tx_power

    @property
    def native_min_value(self) -> float:
        """The node's lower limit once known."""
        status = self.remote.status
        if status is not None and status.tx_power_min is not None:
            return max(0, status.tx_power_min)
        return DEFAULT_TX_RANGE[0]

    @property
    def native_max_value(self) -> float:
        """The node's upper limit once known."""
        status = self.remote.status
        if status is not None and status.tx_power_max is not None:
            return status.tx_power_max
        return DEFAULT_TX_RANGE[1]

    async def async_set_native_value(self, value: float) -> None:
        """Set the power; the node answers "err range" outside its limits."""
        await self._run("txpower", str(round(value)))


class RemoteLed(RemoteEntity, SelectEntity):
    """The node's LED, if it has one (status tells)."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, entry: MeshComConfigEntry, remote: RemoteNode) -> None:
        super().__init__(entry, remote, "led")
        self._attr_options = list(LED_MODES)

    @property
    def available(self) -> bool:
        """Unavailable once the node reported that it has no usable LED."""
        status = self.remote.status
        return status is None or status.led_supported

    @property
    def current_option(self) -> str | None:
        """As last confirmed by the node."""
        return self.remote.led

    async def async_select_option(self, option: str) -> None:
        """Set the LED mode."""
        await self._run("led", option)


class RemoteReachable(RemoteEntity, BinarySensorEntity):
    """Did the node answer the last command?"""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, entry: MeshComConfigEntry, remote: RemoteNode) -> None:
        super().__init__(entry, remote, "reachable")

    @property
    def is_on(self) -> bool | None:
        """None until the first command."""
        return self.remote.reachable

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Whether a command is running."""
        return {"busy": self.remote.busy}


_SENSORS: dict[str, Callable[[RemoteNode], Any]] = {
    "battery": lambda r: r.status.battery if r.status else None,
    "uptime": lambda r: r.status.uptime_minutes if r.status else None,
    "firmware": lambda r: r.status.version if r.status else None,
    "last_answer": lambda r: r.last_answer,
}


class RemoteSensor(RemoteEntity, SensorEntity):
    """Values from the last status answer."""

    def __init__(self, entry: MeshComConfigEntry, remote: RemoteNode, key: str) -> None:
        super().__init__(entry, remote, key)
        self._key = key
        if key == "battery":
            self._attr_device_class = SensorDeviceClass.BATTERY
            self._attr_native_unit_of_measurement = PERCENTAGE
            self._attr_state_class = SensorStateClass.MEASUREMENT
        elif key == "uptime":
            self._attr_device_class = SensorDeviceClass.DURATION
            self._attr_native_unit_of_measurement = UnitOfTime.MINUTES
            self._attr_entity_category = EntityCategory.DIAGNOSTIC
        elif key == "firmware":
            self._attr_entity_category = EntityCategory.DIAGNOSTIC
        elif key == "last_answer":
            self._attr_device_class = SensorDeviceClass.TIMESTAMP
            self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self) -> int | str | datetime | None:
        """Value from the last answer."""
        value: int | str | datetime | None = _SENSORS[self._key](self.remote)
        return value


_FACTORIES: dict[str, Callable[[MeshComConfigEntry, RemoteNode], list[Entity]]] = {
    "button": lambda entry, remote: [
        RemoteButton(entry, remote, cmd) for cmd in ("status", "sendpos", "sendtrack", "reboot")
    ],
    "switch": lambda entry, remote: [RemoteSwitch(entry, remote, name) for name in TOGGLES],
    "number": lambda entry, remote: [RemoteTxPower(entry, remote)],
    "select": lambda entry, remote: [RemoteLed(entry, remote)],
    "binary_sensor": lambda entry, remote: [RemoteReachable(entry, remote)],
    "sensor": lambda entry, remote: [RemoteSensor(entry, remote, key) for key in _SENSORS],
}


@callback
def async_add_remote_entities(
    hass: HomeAssistant,
    entry: MeshComConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
    platform: str,
) -> None:
    """Add the entities of every remote node to its own subentry."""
    for subentry_id, remote in entry.runtime_data.remote.remotes.items():
        entities = _FACTORIES[platform](entry, remote)
        if entities:
            async_add_entities(entities, config_subentry_id=subentry_id)
