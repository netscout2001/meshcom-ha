"""Web API client against a fake node that follows the firmware's contract."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from aiomeshcom.webapi import (
    MeshComWebClient,
    WebApiError,
    WebAuthError,
    WebConnectionError,
    WebThrottledError,
)

PASSWORD = "Secret-Web-19chars"


@dataclass
class FakeNode:
    """Behaves like firmware 4.40a (web_functions.cpp, web_auth.cpp)."""

    password: str | None = PASSWORD
    params: dict[str, str] = field(
        default_factory=lambda: {
            "nomsgall": "off",
            "setgrc": "262;26298;0;0;0;0;",
            "setcall": "DO8RE-12",
            "setpwd": "wlan-secret",
        }
    )
    nonces: set[str] = field(default_factory=set)
    sessions: set[str] = field(default_factory=set)
    fails: int = 0
    requests: list[str] = field(default_factory=list)
    headers_ok: bool = True
    #: Misbehaviour to simulate (see test_misbehaving_node).
    mode: str = "normal"

    def authorised(self, request: web.Request) -> bool:
        if self.password is None:
            return True
        cookie = request.headers.get("Cookie", "")
        return cookie.startswith("mcs=") and cookie[4:] in self.sessions

    async def root(self, request: web.Request) -> web.Response:
        self.requests.append(request.path_qs)
        self.headers_ok &= request.headers.get("X-MC") == "1"
        query = request.query_string
        if query == "loginnonce" and self.mode == "bad_nonce":
            return web.Response(text="not-a-nonce")
        if query.startswith("login=") and self.mode == "login_throttled":
            return web.json_response({"ok": False, "err": "throttled"}, status=403)
        if query.startswith("login=") and self.mode == "login_no_cookie":
            return web.json_response({"ok": True})
        if query.startswith("login=") and self.mode == "login_garbage":
            return web.Response(status=403, text="<html>")
        if query == "logout" and self.mode == "logout_breaks":
            return web.Response(text="x" * 5000)
        if query == "loginnonce":
            if self.fails >= 5:
                return web.json_response({"ok": False, "err": "throttled"}, status=403)
            nonce = secrets.token_hex(16)
            self.nonces.add(nonce)
            return web.Response(text=nonce)
        if query.startswith("login="):
            nonce, _, mac = query[6:].partition(".")
            if nonce not in self.nonces:
                return web.json_response({"ok": False, "err": "nonce"}, status=403)
            self.nonces.discard(nonce)
            assert self.password is not None
            expected = hmac.new(self.password.encode(), nonce.encode(), hashlib.sha256)
            if not hmac.compare_digest(mac, expected.hexdigest()):
                self.fails += 1
                return web.json_response({"ok": False, "err": "badpw"}, status=403)
            token = secrets.token_hex(16)
            self.sessions.add(token)
            return web.json_response(
                {"ok": True},
                headers={"Set-Cookie": f"mcs={token}; Path=/; HttpOnly; SameSite=Strict"},
            )
        if query == "logout":
            cookie = request.headers.get("Cookie", "")
            self.sessions.discard(cookie[4:])
            return web.Response(text="")
        return web.Response(status=404)

    async def getparam(self, request: web.Request) -> web.Response:
        self.requests.append(request.path_qs)
        if not self.authorised(request):
            return web.Response(status=401, text="Unauthorized")
        if self.mode == "server_error":
            return web.Response(status=500)
        if self.mode == "not_json":
            return web.Response(text="<html>")
        if self.mode == "json_list":
            return web.json_response([1, 2])
        name = request.query_string
        if name not in self.params:
            return web.json_response({"returncode": 2, name: ""}, status=422)
        return web.json_response({"returncode": 0, name: self.params[name]})

    async def setparam(self, request: web.Request) -> web.Response:
        self.requests.append(request.path_qs)
        if not self.authorised(request):
            return web.Response(status=401, text="Unauthorized")
        name, _, value = request.query_string.partition("=")
        self.params[name] = value
        return web.json_response({"returncode": 0, name: value})


@pytest.fixture
def node() -> FakeNode:
    return FakeNode()


@pytest.fixture
async def server(node: FakeNode) -> AsyncGenerator[TestServer]:
    app = web.Application()
    app.router.add_get("/", node.root)
    app.router.add_get("/getparam/", node.getparam)
    app.router.add_get("/setparam/", node.setparam)
    test_server = TestServer(app)
    await test_server.start_server()
    yield test_server
    await test_server.close()


@pytest.fixture
async def session() -> AsyncGenerator[aiohttp.ClientSession]:
    async with aiohttp.ClientSession() as client_session:
        yield client_session


def client(
    session: aiohttp.ClientSession, server: TestServer, password: str | None = PASSWORD
) -> MeshComWebClient:
    return MeshComWebClient(session, f"{server.host}:{server.port}", password, timeout=5)


async def test_login_read_logout(
    session: aiohttp.ClientSession, server: TestServer, node: FakeNode
) -> None:
    """Every operation logs in by HMAC and logs out again (F-05)."""
    web_client = client(session, server)
    assert await web_client.get_param("nomsgall") == "off"
    assert node.sessions == set()
    assert node.headers_ok
    assert any(r.startswith("/?login=") for r in node.requests)
    assert node.requests[-1] == "/?logout"
    # The password never travels.
    assert not any(PASSWORD in r for r in node.requests)


async def test_groups(session: aiohttp.ClientSession, server: TestServer) -> None:
    assert await client(session, server).get_groups() == ["262", "26298"]


async def test_status_in_one_session(
    session: aiohttp.ClientSession, server: TestServer, node: FakeNode
) -> None:
    """Switch and groups are read with a single login."""
    assert await client(session, server).get_status() == (False, ["262", "26298"])
    assert sum(r.startswith("/?login=") for r in node.requests) == 1
    with pytest.raises(ValueError, match="not allowed"):
        await client(session, server).get_params(["nomsgall", "setpwd"])


async def test_set_param(
    session: aiohttp.ClientSession, server: TestServer, node: FakeNode
) -> None:
    assert await client(session, server).set_param("nomsgall", "on") == "on"
    assert node.params["nomsgall"] == "on"


async def test_wrong_password(
    session: aiohttp.ClientSession, server: TestServer, node: FakeNode
) -> None:
    with pytest.raises(WebAuthError):
        await client(session, server, "wrong").get_param("nomsgall")
    assert node.fails == 1


async def test_throttled(
    session: aiohttp.ClientSession, server: TestServer, node: FakeNode
) -> None:
    node.fails = 5
    with pytest.raises(WebThrottledError):
        await client(session, server).get_param("nomsgall")


async def test_password_missing_in_home_assistant(
    session: aiohttp.ClientSession, server: TestServer
) -> None:
    """The node has a password, Home Assistant none: 401 becomes an auth error."""
    with pytest.raises(WebAuthError):
        await client(session, server, None).get_param("nomsgall")


async def test_open_node(
    session: aiohttp.ClientSession, server: TestServer, node: FakeNode
) -> None:
    """A node without web password is detected (F-01) and works without login."""
    web_client = client(session, server, None)
    assert not await web_client.is_open()
    node.password = None
    assert await web_client.is_open()
    assert await web_client.get_param("nomsgall") == "off"
    assert not any("login" in r for r in node.requests)


@pytest.mark.parametrize("name", ["setpwd", "setssid", "webpwd", "passwd", "config.json", "x"])
async def test_secret_parameters_are_unreachable(
    session: aiohttp.ClientSession, server: TestServer, node: FakeNode, name: str
) -> None:
    """Secrets can never be requested, not even by mistake (C-04)."""
    with pytest.raises(ValueError, match="not allowed"):
        await client(session, server).get_param(name)
    assert node.requests == []


@pytest.mark.parametrize(("name", "value"), [("nomsgall", "yes"), ("extudpip", "1.2.3.4")])
async def test_write_allowlist(
    session: aiohttp.ClientSession, server: TestServer, node: FakeNode, name: str, value: str
) -> None:
    with pytest.raises(ValueError, match="not allowed"):
        await client(session, server).set_param(name, value)
    assert node.requests == []


async def test_unreachable(session: aiohttp.ClientSession) -> None:
    web_client = MeshComWebClient(session, "127.0.0.1:9", None, timeout=1)
    with pytest.raises(WebConnectionError):
        await web_client.get_param("nomsgall")


async def test_refused_parameter(
    session: aiohttp.ClientSession, server: TestServer, node: FakeNode
) -> None:
    del node.params["setcall"]
    with pytest.raises(WebApiError):
        await client(session, server).get_param("setcall")


async def test_bad_group_list(
    session: aiohttp.ClientSession, server: TestServer, node: FakeNode
) -> None:
    node.params["setgrc"] = "262;<x>;"
    with pytest.raises(WebConnectionError):
        await client(session, server).get_groups()


async def test_garbage_answers(
    session: aiohttp.ClientSession, server: TestServer, node: FakeNode
) -> None:
    """Oversized or malformed answers are rejected, not trusted."""
    web_client = client(session, server, None)
    node.password = None
    node.params["nomsgall"] = "x" * 200
    with pytest.raises(WebConnectionError):
        await web_client.get_param("nomsgall")
    node.params["nomsgall"] = "y" * 5000
    with pytest.raises(WebConnectionError):
        await web_client.get_param("nomsgall")


@pytest.mark.parametrize(
    ("mode", "error"),
    [
        ("bad_nonce", WebConnectionError),
        ("login_throttled", WebThrottledError),
        ("login_no_cookie", WebConnectionError),
        ("login_garbage", WebAuthError),
        ("server_error", WebConnectionError),
        ("not_json", WebConnectionError),
        ("json_list", WebConnectionError),
    ],
)
async def test_misbehaving_node(
    session: aiohttp.ClientSession,
    server: TestServer,
    node: FakeNode,
    mode: str,
    error: type[Exception],
) -> None:
    """Every unexpected answer becomes a defined error, never a crash."""
    node.mode = mode
    with pytest.raises(error):
        await client(session, server).get_param("nomsgall")


async def test_failed_logout_is_ignored(
    session: aiohttp.ClientSession, server: TestServer, node: FakeNode
) -> None:
    """The session expires on its own; a broken logout does not fail the request."""
    node.mode = "logout_breaks"
    assert await client(session, server).get_param("nomsgall") == "off"
