"""Parser tests against real (anonymised) packets captured on 2026-11-06."""

from __future__ import annotations

import pytest

from aiomeshcom import (
    AckMessagePacket,
    DestinationKind,
    InvalidPacketError,
    PositionPacket,
    RemoteManagementPacket,
    SourceType,
    TelemetryPacket,
    TextMessagePacket,
    TimeBeaconPacket,
    parse_datagram,
)
from aiomeshcom.models import Packet


@pytest.fixture(scope="module")
def parsed(node_packets: list[bytes]) -> list[Packet]:
    return [parse_datagram(data) for data in node_packets]


def test_every_node_packet_is_valid(node_packets: list[bytes]) -> None:
    assert len(node_packets) == 161
    for data in node_packets:
        parse_datagram(data)


def test_test_packets_from_other_hosts_are_rejected(capture: list[tuple[str, bytes]]) -> None:
    foreign = [data for address, data in capture if address != "192.0.2.15"]
    assert len(foreign) == 2
    for data in foreign:
        with pytest.raises(InvalidPacketError) as err:
            parse_datagram(data)
        assert err.value.reason == "unknown_type"


def test_packet_type_counts(parsed: list[Packet]) -> None:
    counts: dict[str, int] = {}
    for packet in parsed:
        name = type(packet).__name__
        counts[name] = counts.get(name, 0) + 1
    assert counts == {
        "PositionPacket": 62,
        "TelemetryPacket": 62,
        "TextMessagePacket": 10,
        "AckMessagePacket": 3,
        "RemoteManagementPacket": 7,
        "TimeBeaconPacket": 17,
    }


def _own(parsed: list[Packet], kind: type) -> list[Packet]:
    return [
        p
        for p in parsed
        if isinstance(p, kind) and getattr(p, "source_type", None) is SourceType.NODE
    ]


def test_own_position(parsed: list[Packet]) -> None:
    own = _own(parsed, PositionPacket)
    assert len(own) == 4
    pos = own[0]
    assert isinstance(pos, PositionPacket)
    assert pos.path.originator == "OWN1-12"
    assert pos.path.hops == 0
    assert pos.battery == 96
    assert str(pos.firmware) == "4.40a"
    # 1667 ft
    assert pos.altitude_m == pytest.approx(508.1)
    # Own transmissions carry rssi/snr 0, which is not a measurement.
    assert pos.radio.rssi is None
    assert pos.radio.snr is None


def test_own_telemetry_without_sensors(parsed: list[Packet]) -> None:
    own = _own(parsed, TelemetryPacket)
    assert own
    for tele in own:
        assert isinstance(tele, TelemetryPacket)
        assert not tele.has_sensor_data
        assert tele.battery is None


def test_remote_firmware_is_numeric(parsed: list[Packet]) -> None:
    pos = next(p for p in parsed if isinstance(p, PositionPacket) and p.firmware.minor == 35)
    assert str(pos.firmware) == "4.35p"


def test_battery_zero_means_unknown(parsed: list[Packet]) -> None:
    pos = next(
        p for p in parsed if isinstance(p, PositionPacket) and p.path.originator == "TST5-12"
    )
    assert pos.battery is None


def test_backslash_symbol_table(parsed: list[Packet]) -> None:
    tables = {p.symbol_table for p in parsed if isinstance(p, PositionPacket)}
    assert tables == {"/", "\\"}


def test_real_sensor_telemetry(parsed: list[Packet]) -> None:
    with_sensors = [p for p in parsed if isinstance(p, TelemetryPacket) and p.has_sensor_data]
    assert len(with_sensors) == 10
    tele = with_sensors[0]
    assert tele.temperature_1 == 8
    assert tele.temperature_2 == pytest.approx(3.9)
    assert tele.humidity == 65
    assert tele.pressure_qfe == pytest.approx(962.3)
    # qnh 0 = not reported
    assert tele.pressure_qnh is None
    assert tele.pressure_altitude_m == 433
    assert tele.gas == pytest.approx(543.5)
    assert tele.co2 is None


def test_paths(parsed: list[Packet]) -> None:
    first = parsed[0]
    assert isinstance(first, PositionPacket)
    assert first.path.originator == "TST1-2"
    assert first.path.relays == ("TST2-12", "TST3-12")
    assert first.path.hops == 2
    assert first.radio.rssi == -128
    assert first.radio.snr == -18


def test_direct_messages_carry_sequence(parsed: list[Packet]) -> None:
    direct = [
        p
        for p in parsed
        if isinstance(p, TextMessagePacket) and p.destination_kind is DestinationKind.DIRECT
    ]
    assert [(p.text, p.sequence) for p in direct] == [
        ("Test2", 724),
        ("Test3 mit ACK", 725),
        ("Re Test", 603),
        ("Sample text 5", 106),
    ]
    for message in direct:
        # The sequence number is the counter in the lower 10 bits of the id.
        assert message.sequence == message.msg_id.counter


def test_text_acknowledgements(parsed: list[Packet]) -> None:
    acks = [p for p in parsed if isinstance(p, AckMessagePacket)]
    assert [(a.path.originator, a.acknowledged_station, a.sequence) for a in acks] == [
        ("OWN1-9", "OWN1-12", 724),
        ("OWN1-9", "OWN1-12", 725),
        ("TST33-90", "TST33-92", 106),
    ]
    assert not any(a.rejected for a in acks)


def test_own_messages_share_node_id(parsed: list[Packet]) -> None:
    ids = {
        p.msg_id.node_id
        for p in parsed
        if isinstance(p, (PositionPacket, TextMessagePacket)) and p.source_type is SourceType.NODE
    }
    assert len(ids) == 1


def test_time_beacons(parsed: list[Packet]) -> None:
    beacons = [p for p in parsed if isinstance(p, TimeBeaconPacket)]
    assert len(beacons) == 17
    assert all(b.text.startswith("{CET}") for b in beacons)


def test_server_message_has_no_radio_values(parsed: list[Packet]) -> None:
    message = next(
        p for p in parsed if isinstance(p, TextMessagePacket) and p.source_type is SourceType.UDP
    )
    assert message.destination_kind is DestinationKind.BROADCAST
    assert message.radio.rssi is None
    assert message.text == "Sample text 1"


def test_group_message_from_server(parsed: list[Packet]) -> None:
    group = [
        p
        for p in parsed
        if isinstance(p, TextMessagePacket) and p.destination_kind is DestinationKind.GROUP
    ]
    assert [p.destination for p in group] == ["26298", "26299", "26386", "26298"]
    message = group[0]
    assert message.destination == "26298"
    assert message.source_type is SourceType.UDP
    assert message.sequence is None
    assert message.path.originator == "TST37-99"


def test_other_addressee(parsed: list[Packet]) -> None:
    """A message to a non-callsign addressee ("TEST") is kept, not dropped."""
    other = [
        p
        for p in parsed
        if isinstance(p, TextMessagePacket) and p.destination_kind is DestinationKind.OTHER
    ]
    assert [p.destination for p in other] == ["TEST"]


def test_remote_management(parsed: list[Packet]) -> None:
    """RM1 commands and replies are control traffic, never chat."""
    rm = [p for p in parsed if isinstance(p, RemoteManagementPacket)]
    assert len(rm) == 7
    assert sum(p.is_reply for p in rm) == 2
    assert rm[0].counter == 1793960391
    assert not any(isinstance(p, TextMessagePacket) and p.text.startswith("RM1") for p in parsed)
