"""KISS framing, AX.25 decoding and the TCP connection (firmware 4.40a behaviour).

Frames are built here from test callsigns; no captured traffic of other
stations is used.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import socket
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field

import pytest

from aiomeshcom import (
    AckMessagePacket,
    DestinationKind,
    InvalidOutgoingError,
    InvalidPacketError,
    PositionPacket,
    RemoteManagementPacket,
    SourceType,
    TelemetryPacket,
    TextMessagePacket,
    TimeBeaconPacket,
)
from aiomeshcom.kiss import (
    FEND,
    FESC,
    PORT_DATA,
    PORT_META,
    PORT_SRCINFO,
    PORT_TXRESULT,
    KissDecoder,
    KissDeframer,
    KissTxResult,
    TxStatus,
    _encode_address,
    auth_response,
    build_kiss_message,
    kiss_frame,
    own_message_packet,
    parse_ax25,
    parse_nonce,
)
from aiomeshcom.kiss_client import (
    KEEPALIVE_COUNT,
    KEEPALIVE_IDLE,
    KEEPALIVE_INTERVAL,
    USER_TIMEOUT_MS,
    KissAuthError,
    KissAuthRequiredError,
    KissConnection,
    KissConnectionError,
    KissSendError,
    set_keepalive,
)

OWN = "TST9-9"


def ax25(src: str, info: bytes, digis: tuple[str, ...] = (), dst: str = "APRSMC") -> bytes:
    """An AX.25 UI frame like the node's kissBuildAx25()."""
    frame = _encode_address(dst, last=False, command=True)
    frame += _encode_address(src, last=not digis, command=False)
    for index, digi in enumerate(digis):
        frame += _encode_address(digi, last=index == len(digis) - 1, command=True)
    return frame + b"\x03\xf0" + info


def data(src: str, info: str, digis: tuple[str, ...] = ()) -> bytes:
    return kiss_frame(PORT_DATA, ax25(src, info.encode(), digis))


def meta(rssi: int, snr: int) -> bytes:
    return kiss_frame(
        PORT_META, snr.to_bytes(1, "little", signed=True) + rssi.to_bytes(2, "little", signed=True)
    )


def decode(*frames: bytes, own: str = OWN) -> list[object]:
    decoder = KissDecoder(own)
    result: list[object] = []
    for frame in frames:
        result.extend(decoder.feed(frame))
    result.extend(decoder.flush())
    return result


# --- framing -------------------------------------------------------------------


def test_deframer_escapes_and_splits() -> None:
    payload = bytes([0x00, FEND, 0x41, FESC, 0x42])
    framed = kiss_frame(PORT_DATA, payload[1:])
    deframer = KissDeframer()
    # Byte by byte, with noise and empty frames in between.
    frames: list[bytes] = []
    for byte in b"\xc0\xc0" + framed + framed:
        frames.extend(deframer.feed(bytes([byte])))
    assert frames == [payload, payload]


def test_deframer_drops_oversized_and_bad_escape() -> None:
    deframer = KissDeframer(max_frame=8)
    assert deframer.feed(bytes([FEND]) + b"x" * 20 + bytes([FEND])) == []
    assert deframer.feed(bytes([FEND, 0x00, FESC, 0x41, FEND])) == []
    assert deframer.dropped == 2
    assert deframer.feed(bytes([FEND, 0x00, 0x41, FEND])) == [b"\x00\x41"]


# --- AX.25 ---------------------------------------------------------------------


def test_parse_ax25() -> None:
    frame = parse_ax25(ax25("TST1-12", b":x", ("RLY1-1", "RLY2-12")))
    assert frame.destination == "APRSMC"
    assert (frame.source_base, frame.source_ssid) == ("TST1", 12)
    assert frame.digipeaters == ("RLY1-1", "RLY2-12")
    assert frame.info == b":x"


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        (b"\x82" * 7, "ax25_address"),  # unterminated
        (bytes(ord(c) << 1 for c in "APRSMC") + b"\x61", "ax25_address"),  # one address
        (bytes(ord(c) << 1 for c in "AP?RSM") + b"\x60" + b"\x00" * 9, "ax25_address"),
        (bytes([0x83]) + b"\x82" * 5 + b"\x60" + b"\x00" * 9, "ax25_address"),  # ext bit early
        (bytes(ord(c) << 1 for c in "AP RSM") + b"\x60" + b"\x00" * 9, "ax25_address"),
        (bytes(ord(c) << 1 for c in "      ") + b"\x60" + b"\x00" * 9, "ax25_address"),
    ],
)
def test_parse_ax25_bad_address(raw: bytes, reason: str) -> None:
    with pytest.raises(InvalidPacketError) as err:
        parse_ax25(raw)
    assert err.value.reason == reason


def test_parse_ax25_not_ui_or_too_many() -> None:
    frame = ax25("TST1-1", b"x")
    with pytest.raises(InvalidPacketError, match="ax25_not_ui"):
        parse_ax25(frame[:14] + b"\x3f\xf0x")
    with pytest.raises(InvalidPacketError, match="ax25_address"):
        parse_ax25(frame[:14])
    many = _encode_address("APRSMC", last=False, command=True) * 11
    with pytest.raises(InvalidPacketError, match="ax25_address"):
        parse_ax25(many)


# --- decoding --------------------------------------------------------------------


def test_position_with_tags_and_meta() -> None:
    info = "!5003.00N/00851.00E>Test Node#TST1-12/B=096/A=001713/N4/R=262;20;"
    packets = decode(data("TST1-12", info, ("RLY1-12",)), meta(-83, 11))
    assert len(packets) == 1
    position = packets[0]
    assert isinstance(position, PositionPacket)
    assert position.source_type is SourceType.LORA
    assert position.path.originator == "TST1-12"
    assert position.path.relays == ("RLY1-12",)
    assert position.latitude == pytest.approx(50.05, abs=1e-4)
    assert position.longitude == pytest.approx(8.85, abs=1e-4)
    assert position.altitude_m == pytest.approx(522.1, abs=0.1)
    assert position.battery == 96
    assert position.symbol == ">"
    assert position.symbol_table == "/"
    assert (position.radio.rssi, position.radio.snr) == (-83, 11)


def test_position_variants() -> None:
    packets = decode(
        data("TST1-1", "!4814.73S\\01122.16W-/A=00500"),  # metres, south/west
        data("TST2-1", "=5010.00N/00915.00E#no tags at all"),
        data("TST3-1", "!5010.00N/00915.00E#/B=150/A=12x"),  # odd values
    )
    first, second, third = packets
    assert isinstance(first, PositionPacket)
    assert first.latitude is not None
    assert first.latitude < 0
    assert first.longitude is not None
    assert first.longitude < 0
    assert first.symbol_table == "\\"
    assert first.altitude_m == pytest.approx(500, abs=0.5)
    assert first.radio.rssi is None  # no meta frame
    assert isinstance(second, PositionPacket)
    assert second.altitude_m is None
    assert second.battery is None
    assert isinstance(third, PositionPacket)
    assert third.battery is None
    assert third.altitude_m is None


def test_own_position_with_telemetry() -> None:
    info = "!5003.00N/00851.00E>Mobile#TST9-9/B=100/A=001680/P=964.6/H=29.0/T=17.7/O=x/F=413"
    packets = decode(data(OWN, info), meta(99, 0))
    position, telemetry = packets
    assert isinstance(position, PositionPacket)
    assert position.source_type is SourceType.NODE
    assert position.radio.rssi is None
    assert isinstance(telemetry, TelemetryPacket)
    assert telemetry.temperature_1 == pytest.approx(17.7)
    assert telemetry.humidity == pytest.approx(29.0)
    assert telemetry.pressure_qfe == pytest.approx(964.6)
    assert telemetry.temperature_2 is None
    assert telemetry.battery == 100


def test_other_station_position_with_weather() -> None:
    """Weather tags of other stations become telemetry too (station weather)."""
    info = "!5003.00N/00851.00E#WX/B=080/T=4.5/H=92.0/Q=1021.4"
    packets = decode(data("TST3-12", info), meta(-112, -6))
    position, telemetry = packets
    assert isinstance(position, PositionPacket)
    assert position.source_type is SourceType.LORA
    assert isinstance(telemetry, TelemetryPacket)
    assert telemetry.source_type is SourceType.LORA
    assert telemetry.path.originator == "TST3-12"
    assert telemetry.temperature_1 == pytest.approx(4.5)
    assert telemetry.humidity == pytest.approx(92.0)
    assert telemetry.pressure_qnh == pytest.approx(1021.4)


def test_own_position_without_sensors_has_no_telemetry() -> None:
    packets = decode(data(OWN, "!5003.00N/00851.00E>Mobile/B=100"))
    assert len(packets) == 1


def test_server_relay_marker() -> None:
    packets = decode(data("TST1-12", ":         :hello"), meta(99, 0))
    message = packets[0]
    assert isinstance(message, TextMessagePacket)
    assert message.source_type is SourceType.UDP
    assert message.radio.rssi is None


def test_messages() -> None:
    packets = decode(
        data("TST1-12", ":         :an alle"),
        data("TST1-12", ":262      :Gruppe \u00e4\U0001f600"),
        data("TST1-12", f":{OWN:<9}:hallo{{123"),
        data("TST1-12", ":TEST     :LORATX 7"),
    )
    broadcast, group, direct, other = packets
    assert isinstance(broadcast, TextMessagePacket)
    assert broadcast.destination == "*"
    assert broadcast.destination_kind is DestinationKind.BROADCAST
    assert isinstance(group, TextMessagePacket)
    assert group.destination == "262"
    assert group.text == "Gruppe \u00e4\U0001f600"
    assert isinstance(direct, TextMessagePacket)
    assert direct.destination == OWN
    assert direct.text == "hallo"
    assert direct.sequence == 123
    assert isinstance(other, TextMessagePacket)
    assert other.destination_kind is DestinationKind.OTHER


def test_control_messages() -> None:
    packets = decode(
        data("TST1-12", f":{OWN:<9}:ack42"),
        data("TST1-12", f":{OWN:<9}:rej7"),
        data("TST1-12", ":         :{CET}2026-11-06 10:38:52"),
        data("TST1-12", f":{OWN:<9}:RM1 1793961367 status abcdef"),
    )
    ack, rej, beacon, remote = packets
    assert isinstance(ack, AckMessagePacket)
    assert (ack.acknowledged_station, ack.sequence, ack.rejected) == (OWN, 42, False)
    assert isinstance(rej, AckMessagePacket)
    assert rej.rejected is True
    assert isinstance(beacon, TimeBeaconPacket)
    assert isinstance(remote, RemoteManagementPacket)


def test_full_callsign_from_port_2() -> None:
    srcinfo = kiss_frame(PORT_SRCINFO, b"TST1-33")
    packets = decode(
        srcinfo,
        data("TST1-15", ":         :x"),
        # Port 2 for another base call does not apply.
        kiss_frame(PORT_SRCINFO, b"OTHR-33"),
        data("TST1-15", ":         :y"),
        # An invalid port-2 call is ignored.
        kiss_frame(PORT_SRCINFO, b"<b>-33"),
        data("TST1-15", ":         :z"),
    )
    assert [p.path.originator for p in packets] == ["TST1-33", "TST1-15", "TST1-15"]  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("frame", "reason"),
    [
        (kiss_frame(PORT_DATA, ax25("TST1-1", b":short")), "kiss_message"),
        (kiss_frame(PORT_DATA, ax25("TST1-1", b">status text")), "kiss_payload_type"),
        (kiss_frame(PORT_DATA, ax25("TST1-1", b"!garbage")), "kiss_position"),
        (kiss_frame(PORT_DATA, ax25("TST1-1", b"!9103.00N/00851.00E>")), "kiss_position"),
        (kiss_frame(PORT_DATA, ax25("TST1-1", b"!5003.00N/18101.00E>")), "kiss_position"),
        (kiss_frame(PORT_DATA, ax25("TST1-1", b":         :\xff\xfe")), "encoding"),
        (kiss_frame(PORT_DATA, ax25("TST1-1", b":<script> :x")), "field_dst"),
        (kiss_frame(PORT_DATA, b"\x01\x02"), "ax25_address"),
        (kiss_frame(5, b"x"), "kiss_port"),
        (bytes([FEND, 0x01, 0x00, FEND]), "kiss_command"),
        (kiss_frame(PORT_META, b"\x00"), "kiss_meta"),
    ],
)
def test_invalid_frames_counted(frame: bytes, reason: str) -> None:
    decoder = KissDecoder(OWN)
    assert decoder.feed(frame) + decoder.flush() == []
    assert decoder.invalid == {reason: 1}


def test_meta_without_data_and_bad_meta_flushes() -> None:
    decoder = KissDecoder(OWN)
    assert decoder.feed(meta(-80, 5)) == []
    decoder.feed(data("TST1-1", ":         :x"))
    assert decoder.has_pending
    packets = decoder.feed(kiss_frame(PORT_META, b"\x01"))
    assert len(packets) == 1
    assert not decoder.has_pending


def test_tx_results() -> None:
    decoder = KissDecoder(OWN)
    results = decoder.feed(
        kiss_frame(PORT_TXRESULT, bytes([TxStatus.OK]) + (0x63CF32D4).to_bytes(4, "little"))
        + kiss_frame(PORT_TXRESULT, bytes([TxStatus.RATE_LIMIT]))
        + bytes([FEND, PORT_TXRESULT << 4, FEND])
    )
    assert results == [
        KissTxResult(TxStatus.OK, 0x63CF32D4),
        KissTxResult(TxStatus.RATE_LIMIT, None),
        KissTxResult(TxStatus.BAD_FRAME, None),
    ]
    first, second, _ = results
    assert isinstance(first, KissTxResult)
    assert first.ok
    assert isinstance(second, KissTxResult)
    assert not second.ok


def test_local_ids_are_unique() -> None:
    packets = decode(data("TST1-1", ":         :a"), data("TST1-1", ":         :a"))
    ids = {p.msg_id.value for p in packets}  # type: ignore[attr-defined]
    assert len(ids) == 2


# --- sending -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("destination", "sequence", "expected_info"),
    [
        ("*", None, b":         :Hallo"),
        ("262", None, b":262      :Hallo"),
        ("TST1-12", 17, b":TST1-12  :Hallo{17"),
    ],
)
def test_build_message(destination: str, sequence: int | None, expected_info: bytes) -> None:
    frame = build_kiss_message(OWN, destination, "Hallo", sequence)
    raw = KissDeframer().feed(frame)[0]
    assert raw[0] == 0x00
    parsed = parse_ax25(raw[1:])
    assert (parsed.source_base, parsed.source_ssid) == ("TST9", 9)
    assert parsed.digipeaters == ()
    assert parsed.info == expected_info


@pytest.mark.parametrize(
    ("own", "destination", "text", "sequence", "reason"),
    [
        (OWN, "*", "a\nb", None, "text_control_characters"),
        (OWN, "*", "x" * 151, None, "text_too_long"),
        (OWN, "<b>", "x", None, "destination"),
        (OWN, "*", "{CET}x", None, "text_reserved_prefix"),
        (OWN, "*", "x", 5, "sequence"),
        (OWN, "TST1-1", "x", 1000, "sequence"),
        ("TST9-33", "*", "x", None, "callsign"),
        ("bad", "*", "x", None, "callsign"),
    ],
)
def test_build_message_rejected(
    own: str, destination: str, text: str, sequence: int | None, reason: str
) -> None:
    with pytest.raises(InvalidOutgoingError) as err:
        build_kiss_message(own, destination, text, sequence)
    assert err.value.reason == reason


def test_own_message_packet() -> None:
    packet = own_message_packet(OWN, "TST1-12", "Hallo", 17, 0x63CF32D4)
    assert packet.source_type is SourceType.NODE
    assert packet.sequence == 17
    assert packet.text == "Hallo"
    assert str(packet.msg_id) == "63CF32D4"


# --- authentication ------------------------------------------------------------


def test_auth_helpers() -> None:
    nonce = bytes(range(16))
    assert parse_nonce(b"NONCE: " + nonce.hex().encode() + b"\r\n") == nonce
    assert parse_nonce(b"NONCE: 1234\r\n") is None
    expected = hmac.new(b"geheim", nonce, hashlib.sha256).hexdigest().encode() + b"\r\n"
    assert auth_response("geheim", nonce) == expected
    assert auth_response("geheim  ", nonce) == expected  # node strips trailing spaces
    for bad in ("", "x" * 15, "pa\u00df"):
        with pytest.raises(InvalidOutgoingError):
            auth_response(bad, nonce)


# --- connection against a fake node --------------------------------------------


@dataclass
class FakeKissNode:
    """Behaves like kiss_functions.cpp of firmware 4.40a."""

    password: str | None = "geheim"
    mode: str = "normal"
    received: list[bytes] = field(default_factory=list)
    writer: asyncio.StreamWriter | None = None
    tx_status: int = TxStatus.OK

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.writer = writer
        if self.mode == "silent":
            await asyncio.sleep(10)
            return
        if self.mode == "close_after_nonce":
            writer.write(b"NONCE: " + bytes(range(16)).hex().encode() + b"\r\n")
            await writer.drain()
            await reader.readline()
            writer.close()
            return
        if self.mode == "garbage":
            writer.write(b"NONCE: nothex\r\n")
            await writer.drain()
            await asyncio.sleep(10)
            return
        if self.password is not None:
            nonce = bytes(range(16))
            writer.write(b"NONCE: " + nonce.hex().encode() + b"\r\n")
            await writer.drain()
            if self.mode == "no_answer":
                await asyncio.sleep(10)
                return
            line = await reader.readline()
            expected = hmac.new(self.password.encode(), nonce, hashlib.sha256).hexdigest()
            if self.mode == "weird":
                writer.write(b"HUH\r\n")
            elif line.strip().decode() == expected:
                # Some data right behind OK, in the same segment.
                writer.write(b"OK\r\n" + data("TST1-12", ":         :hinter OK"))
            else:
                writer.write(b"FAIL\r\n")
                await writer.drain()
                writer.close()
                return
            await writer.drain()
        deframer = KissDeframer()
        while chunk := await reader.read(1024):
            for frame in deframer.feed(chunk):
                self.received.append(frame)
                if self.mode == "no_result":
                    continue
                result = bytes([self.tx_status])
                if self.tx_status == TxStatus.OK:
                    result += (0x63CF3000 + len(self.received)).to_bytes(4, "little")
                writer.write(kiss_frame(PORT_TXRESULT, result))
                await writer.drain()
        writer.close()

    def push(self, frame: bytes) -> None:
        assert self.writer is not None
        self.writer.write(frame)


@pytest.fixture
def fake() -> FakeKissNode:
    return FakeKissNode()


@pytest.fixture
async def server(fake: FakeKissNode) -> AsyncGenerator[asyncio.Server]:
    server = await asyncio.start_server(fake.handle, "127.0.0.1", 0)
    yield server
    server.close()


def _port(server: asyncio.Server) -> int:
    return int(server.sockets[0].getsockname()[1])


async def test_connect_auth_receive_send(server: asyncio.Server, fake: FakeKissNode) -> None:
    packets: list[object] = []
    connection = KissConnection(
        "127.0.0.1", OWN, "geheim", packets.append, port=_port(server), connect_timeout=2
    )
    await connection.connect()
    assert connection.authenticated is True
    task = asyncio.create_task(connection.run())
    await asyncio.sleep(0.05)
    fake.push(data("TST1-12", ":262      :live") + meta(-90, 4))
    await asyncio.sleep(0.05)

    own = await connection.send_text("TST1-12", "Hallo", direct=True)
    assert isinstance(own, TextMessagePacket)
    assert own.source_type is SourceType.NODE
    assert own.sequence is not None
    group = await connection.send_text("262", "GM", direct=False)
    assert isinstance(group, TextMessagePacket)
    assert group.sequence is None

    texts = [p.text for p in packets if isinstance(p, TextMessagePacket)]
    assert texts == ["hinter OK", "live", "Hallo", "GM"]
    live = packets[1]
    assert isinstance(live, TextMessagePacket)
    assert live.radio.rssi == -90
    assert len(fake.received) == 2
    assert parse_ax25(fake.received[0][1:]).info.startswith(b":TST1-12  :Hallo{")

    fake.tx_status = TxStatus.TX_OFF
    with pytest.raises(KissSendError) as err:
        await connection.send_text("*", "x", direct=False)
    assert err.value.status == TxStatus.TX_OFF

    await connection.close()
    with pytest.raises(KissConnectionError):
        await task
    assert connection.invalid_frames == {}


async def test_flush_timer_emits_without_meta(server: asyncio.Server, fake: FakeKissNode) -> None:
    fake.password = None
    packets: list[object] = []
    connection = KissConnection("127.0.0.1", OWN, None, packets.append, port=_port(server))
    await connection.connect()
    assert connection.authenticated is False
    task = asyncio.create_task(connection.run())
    await asyncio.sleep(0.05)
    fake.push(data("TST1-12", ":         :ohne meta"))
    await asyncio.sleep(0.5)
    assert len(packets) == 1
    await connection.close()
    with pytest.raises(KissConnectionError):
        await task


async def test_wrong_password(server: asyncio.Server) -> None:
    connection = KissConnection("127.0.0.1", OWN, "falsch", print, port=_port(server))
    with pytest.raises(KissAuthError):
        await connection.connect()


async def test_password_required(server: asyncio.Server) -> None:
    connection = KissConnection("127.0.0.1", OWN, None, print, port=_port(server))
    with pytest.raises(KissAuthRequiredError):
        await connection.connect()


@pytest.mark.parametrize("mode", ["weird", "garbage"])
async def test_bad_handshake(server: asyncio.Server, fake: FakeKissNode, mode: str) -> None:
    fake.mode = mode
    connection = KissConnection("127.0.0.1", OWN, "geheim", print, port=_port(server))
    with pytest.raises(KissConnectionError):
        await connection.connect()


async def test_no_auth_answer(
    server: asyncio.Server, fake: FakeKissNode, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake.mode = "no_answer"
    monkeypatch.setattr("aiomeshcom.kiss_client.AUTH_ANSWER_TIMEOUT", 0.1)
    connection = KissConnection("127.0.0.1", OWN, "geheim", print, port=_port(server))
    with pytest.raises(KissConnectionError, match="no answer"):
        await connection.connect()


async def test_silent_node_means_no_auth(
    server: asyncio.Server, fake: FakeKissNode, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No challenge within the wait: the node does not enforce authentication."""
    fake.mode = "silent"
    monkeypatch.setattr("aiomeshcom.kiss_client.CHALLENGE_TIMEOUT", 0.1)
    connection = KissConnection("127.0.0.1", OWN, "geheim", print, port=_port(server))
    await connection.connect()
    assert connection.authenticated is False
    await connection.close()


async def test_send_without_result(
    server: asyncio.Server, fake: FakeKissNode, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake.mode = "no_result"
    monkeypatch.setattr("aiomeshcom.kiss_client.TX_RESULT_TIMEOUT", 0.1)
    connection = KissConnection("127.0.0.1", OWN, "geheim", print, port=_port(server))
    await connection.connect()
    task = asyncio.create_task(connection.run())
    with pytest.raises(KissSendError) as err:
        await connection.send_text("*", "x", direct=False)
    assert err.value.status is None
    await connection.close()
    with pytest.raises(KissConnectionError):
        await task


async def test_not_connected_and_unreachable() -> None:
    connection = KissConnection("127.0.0.1", OWN, None, print, port=1, connect_timeout=1)
    with pytest.raises(KissConnectionError):
        await connection.run()
    with pytest.raises(KissConnectionError):
        await connection.send_text("*", "x", direct=False)
    with pytest.raises(KissConnectionError):
        await connection.connect()
    await connection.close()


async def test_node_closes_connection(server: asyncio.Server, fake: FakeKissNode) -> None:
    connection = KissConnection("127.0.0.1", OWN, "geheim", print, port=_port(server))
    await connection.connect()
    task = asyncio.create_task(connection.run())
    await asyncio.sleep(0.05)
    assert fake.writer is not None
    fake.writer.close()
    with pytest.raises(KissConnectionError, match="closed by node"):
        await task
    await connection.close()


async def test_node_closes_during_auth(server: asyncio.Server, fake: FakeKissNode) -> None:
    fake.mode = "close_after_nonce"
    connection = KissConnection("127.0.0.1", OWN, "geheim", print, port=_port(server))
    with pytest.raises(KissConnectionError, match="unexpected answer"):
        await connection.connect()


async def test_connection_reset_while_reading(server: asyncio.Server, fake: FakeKissNode) -> None:
    connection = KissConnection("127.0.0.1", OWN, "geheim", print, port=_port(server))
    await connection.connect()
    task = asyncio.create_task(connection.run())
    await asyncio.sleep(0.05)
    assert fake.writer is not None
    fake.writer.transport.abort()
    with pytest.raises(KissConnectionError):
        await task
    await connection.close()


async def test_connection_lost_while_sending(server: asyncio.Server, fake: FakeKissNode) -> None:
    fake.mode = "no_result"
    connection = KissConnection("127.0.0.1", OWN, "geheim", print, port=_port(server))
    await connection.connect()
    task = asyncio.create_task(connection.run())
    send = asyncio.create_task(connection.send_text("*", "x", direct=False))
    await asyncio.sleep(0.1)
    assert fake.writer is not None
    fake.writer.close()
    with pytest.raises(KissConnectionError):
        await send
    with pytest.raises(KissConnectionError):
        await task
    await connection.close()


def test_own_callsign_over_the_air_is_not_own() -> None:
    """Our callsign with a measured RSSI is another station, not the node."""
    packets = decode(data(OWN, "!5003.00N/00851.00E>fake/B=100"), meta(-95, 3))
    position = packets[0]
    assert isinstance(position, PositionPacket)
    assert position.source_type is SourceType.LORA
    assert len(packets) == 1  # no telemetry for the own node either


async def test_keepalive_detects_dead_node(server: asyncio.Server) -> None:
    """The connection probes an idle node: lost after about 2 minutes, not 2 hours."""
    connection = KissConnection("127.0.0.1", OWN, "geheim", print, port=_port(server))
    await connection.connect()
    try:
        assert connection._writer is not None
        sock = connection._writer.get_extra_info("socket")
        assert sock.getsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE) == 1
        if hasattr(socket, "TCP_KEEPIDLE"):  # Linux, as in Home Assistant OS
            assert sock.getsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE) == KEEPALIVE_IDLE
            assert sock.getsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL) == KEEPALIVE_INTERVAL
            assert sock.getsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT) == KEEPALIVE_COUNT
            assert sock.getsockopt(socket.IPPROTO_TCP, socket.TCP_USER_TIMEOUT) == USER_TIMEOUT_MS
        assert KEEPALIVE_IDLE + KEEPALIVE_INTERVAL * KEEPALIVE_COUNT <= 150
    finally:
        await connection.close()


def test_set_keepalive_tolerates_missing_options() -> None:
    """A platform rejecting an option does not break the connection set-up."""

    class Strict:
        def __init__(self) -> None:
            self.calls: list[tuple[int, int, int]] = []

        def setsockopt(self, level: int, option: int, value: int) -> None:
            self.calls.append((level, option, value))
            if level == socket.IPPROTO_TCP:
                raise OSError("not supported")

    sock = Strict()
    set_keepalive(sock)  # type: ignore[arg-type]
    assert (socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1) in sock.calls
