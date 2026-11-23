"""Net console client against a fake node (firmware ``src/net_console.cpp``)."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import socket
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field

import pytest

from aiomeshcom import InvalidOutgoingError
from aiomeshcom.netconsole import (
    CREDENTIALS,
    HARDWARE,
    IDENTITY,
    MAX_LINE_CHARS,
    RADIO,
    SECURITY,
    SYSTEM,
    UNREACHABLE,
    ConsoleAuthError,
    ConsoleAuthRequiredError,
    ConsoleError,
    ConsoleProtocolError,
    ConsoleRefusedError,
    ConsoleUnreachableError,
    NetConsole,
    RadioInfo,
    clean_line,
    command_risk,
    parse_radio_info,
    validate_command,
)

NONCE = bytes(range(16))


@dataclass
class FakeConsole:
    password: str | None = "geheim"
    mode: str = "normal"
    received: list[bytes] = field(default_factory=list)
    writer: asyncio.StreamWriter | None = None

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.writer = writer
        if self.mode == "garbage":
            writer.write(b"HELLO\r\n")
            await writer.drain()
            return
        if self.mode == "silent":
            await asyncio.sleep(30)
            return
        if self.password is None:
            writer.write(b"OK\r\nMeshCom Console\r\n")
        else:
            writer.write(b"NONCE: " + NONCE.hex().encode() + b"\r\n")
            await writer.drain()
            line = (await reader.readline()).strip().decode()
            expected = hmac.new(self.password.encode(), NONCE, hashlib.sha256).hexdigest()
            if self.mode == "weird":
                writer.write(b"HUH\r\n")
            elif line == expected:
                writer.write(b"OK\r\nMeshCom Console\r\nType --help for commands\r\n")
            else:
                writer.write(b"FAIL\r\n")
                await writer.drain()
                writer.close()
                return
        await writer.drain()
        while line_in := await reader.readline():
            self.received.append(line_in)
            writer.write(b"echo " + line_in.strip() + b"\r\n")
            await writer.drain()
        writer.close()


@pytest.fixture
def fake() -> FakeConsole:
    return FakeConsole()


@pytest.fixture
async def server(fake: FakeConsole) -> AsyncGenerator[asyncio.Server]:
    server = await asyncio.start_server(fake.handle, "127.0.0.1", 0)
    yield server
    server.close()


def _port(server: asyncio.Server) -> int:
    return int(server.sockets[0].getsockname()[1])


async def test_login_send_and_close(server: asyncio.Server, fake: FakeConsole) -> None:
    lines: list[str] = []
    console = NetConsole("127.0.0.1", "geheim", lines.append, port=_port(server))
    await console.connect()
    assert console.connected
    assert not console.open_access
    task = asyncio.create_task(console.run())
    await console.send("  --info  ")
    await asyncio.sleep(0.1)
    assert fake.received == [b"--info\n"]
    assert lines == ["MeshCom Console", "Type --help for commands", "echo --info"]
    # The node ends the session (another login, restart).
    assert fake.writer is not None
    fake.writer.close()
    await asyncio.wait_for(task, 2)
    assert not console.connected
    with pytest.raises(ConsoleError):
        await console.send("--info")
    with pytest.raises(ConsoleError):
        await console.run()
    await console.close()


async def test_open_access(server: asyncio.Server, fake: FakeConsole) -> None:
    fake.password = None
    lines: list[str] = []
    console = NetConsole("127.0.0.1", None, lines.append, port=_port(server))
    await console.connect()
    assert console.open_access
    task = asyncio.create_task(console.run())
    await asyncio.sleep(0.05)
    assert lines == ["MeshCom Console"]
    await console.close()
    await asyncio.wait_for(task, 2)


async def test_wrong_password(server: asyncio.Server) -> None:
    console = NetConsole("127.0.0.1", "falsch", print, port=_port(server))
    with pytest.raises(ConsoleAuthError):
        await console.connect()


async def test_password_too_long(server: asyncio.Server) -> None:
    console = NetConsole("127.0.0.1", "x" * 20, print, port=_port(server))
    with pytest.raises(ConsoleAuthError):
        await console.connect()


async def test_password_required(server: asyncio.Server) -> None:
    console = NetConsole("127.0.0.1", None, print, port=_port(server))
    with pytest.raises(ConsoleAuthRequiredError):
        await console.connect()


@pytest.mark.parametrize("mode", ["garbage", "weird"])
async def test_protocol_errors(server: asyncio.Server, fake: FakeConsole, mode: str) -> None:
    fake.mode = mode
    console = NetConsole("127.0.0.1", "geheim", print, port=_port(server))
    with pytest.raises(ConsoleProtocolError):
        await console.connect()


async def test_silent_node(
    server: asyncio.Server, fake: FakeConsole, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake.mode = "silent"
    monkeypatch.setattr("aiomeshcom.netconsole.HANDSHAKE_TIMEOUT", 0.2)
    console = NetConsole("127.0.0.1", "geheim", print, port=_port(server))
    with pytest.raises(ConsoleProtocolError):
        await console.connect()


async def test_refused() -> None:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    console = NetConsole("127.0.0.1", None, print, port=port)
    with pytest.raises(ConsoleRefusedError):
        await console.connect()


async def test_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fail(*_args: object, **_kwargs: object) -> None:
        raise OSError("no route")

    monkeypatch.setattr("asyncio.open_connection", _fail)
    console = NetConsole("192.0.2.1", None, print)
    with pytest.raises(ConsoleUnreachableError):
        await console.connect()


async def test_long_and_partial_lines() -> None:
    lines: list[str] = []
    console = NetConsole("127.0.0.1", None, lines.append)
    reader = asyncio.StreamReader(limit=64)
    reader.feed_data(b"a" * 100 + b"\nfine\r\nrest")
    reader.feed_eof()
    console._reader = reader  # drive run() without a socket
    await console.run()
    assert lines[0] == "a" * 100
    assert "fine" in lines
    assert lines[-1] == "rest"


def test_clean_line() -> None:
    assert clean_line(b"ok\r\n") == "ok"
    assert clean_line(b"a\x1b[31mb\tc") == "a�[31mb\tc"
    assert clean_line(b"\xff") == "�"
    assert len(clean_line(b"x" * 1000)) == MAX_LINE_CHARS


@pytest.mark.parametrize(
    ("command", "risk"),
    [
        ("--info", None),
        ("--setnet hamnet", None),
        ("--reboot", None),
        ("--passwd x", CREDENTIALS),
        ("--WEBPWD x", CREDENTIALS),
        ("--setssid net", UNREACHABLE),
        ("--deepsleep", UNREACHABLE),
        ("--ota-update", UNREACHABLE),
        ("--setcall X1ABC-1", IDENTITY),
        ("info", None),
        # The firmware runs every "--" in a line as its own command.
        ("--info --setssid x", UNREACHABLE),
        ("--setname a--passwd b", CREDENTIALS),
        ("--txpower 5 --passwd b --deepsleep", UNREACHABLE),
        ("--setname a-b", IDENTITY),  # a single "-" does not split
        ("--info ---setssid", UNREACHABLE),
        ("--wifiap on", UNREACHABLE),
        ("--wifiap off", None),
        ("--KISS OFF", UNREACHABLE),
        ("--kiss tx off", None),
        ("--kiss", None),
        ("--extudp off", UNREACHABLE),
        ("--extudp on", None),
        ("--extudpip 192.0.2.1", UNREACHABLE),
        ("--netconsole off", UNREACHABLE),
        ("--setownip 192.0.2.5", UNREACHABLE),
        ("--setowngw 192.0.2.1", UNREACHABLE),
        ("--setownms 255.255.255.0", UNREACHABLE),
        ("--setowndns 192.0.2.1", UNREACHABLE),
        ("--setownntp 192.0.2.1", None),
        ("--btcode 123456", CREDENTIALS),  # the second "--" starts it
        ("--aprsis pass 12345", CREDENTIALS),
        ("--APRSIS PASS 12345", CREDENTIALS),
        ("--aprsis server example.org", None),
        ("--aprswx on", None),
        ("--txpower 22", RADIO),
        ("--txfreq 433.175", RADIO),
        ("--txsf 11", RADIO),
        ("--setboostedgain on", RADIO),
        ("--gpio 5 on", HARDWARE),
        ("--gpiocontrol on", HARDWARE),
        ("--relay off", HARDWARE),
        ("--button gpio 12", HARDWARE),
        ("--setlat 47.9", IDENTITY),
        ("--setudpcall QX1YZ-1", IDENTITY),
        ("--aprswxcall QX1YZ-13", IDENTITY),
        ("--kiss auth off", SECURITY),
        ("--kiss auth on", None),
        ("--remotemgmt on", SECURITY),
        ("--cleanflash", SYSTEM),
        ("--spiffs reset", SYSTEM),
        ("--dfu", SYSTEM),
        ("--wifi off", UNREACHABLE),
        ("--wifi on", None),
        ("--netmode eth", UNREACHABLE),
        ("--gpiox", None),  # the node runs no command for it
        ("--info --gpio 5 on --setssid x", UNREACHABLE),  # the most severe wins
        ("--gpio 5 on --txsf 7", RADIO),
    ],
)
def test_command_risk(command: str, risk: str | None) -> None:
    assert command_risk(command) == risk


@pytest.mark.parametrize(
    "command", ["info", "--", "--info\n--reboot", "--info\x00", "--" + "x" * 200, "--ä"]
)
def test_invalid_commands(command: str) -> None:
    with pytest.raises(InvalidOutgoingError):
        validate_command(command)


INFO = [
    "...DISPLAY on",
    "...CTRY EU8",
    "...FREQ 433.1750 MHz TXPWR 22 dBm RXBOOST off",
    "...PASSWD <secret>",
]


def test_parse_radio_info() -> None:
    assert parse_radio_info(INFO) == RadioInfo(433.175, 22, False, "EU8")
    on = ["...FREQ 433.1750 MHz TXPWR 30 dBm RXBOOST on"]
    assert parse_radio_info(on) == RadioInfo(433.175, 30, True, None)
    # Firmware without RXBOOST.
    assert parse_radio_info(["...FREQ 869.5250 MHz TXPWR 14 dBm"]) == RadioInfo(
        869.525, 14, None, None
    )
    # The last radio line wins.
    assert parse_radio_info([*INFO, on[0]]) == RadioInfo(433.175, 30, True, "EU8")


@pytest.mark.parametrize(
    "line",
    [
        "",
        "...FREQ 433.1750 MHz TXPWR 22 dBm RXBOOST maybe",
        "...FREQ 50.0000 MHz TXPWR 22 dBm",
        "...FREQ 2400.0000 MHz TXPWR 22 dBm",
        "...FREQ 433.1750 MHz TXPWR 99 dBm",
        "...FREQ 433.1750 MHz TXPWR -20 dBm",
        "echo ...FREQ 433.1750 MHz TXPWR 22 dBm",
        "...CTRY EU8",
    ],
)
def test_parse_radio_info_rejects(line: str) -> None:
    assert parse_radio_info([line]) is None
