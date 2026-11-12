"""Web API client against a fake node that follows the firmware's contract."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from typing import Any

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from aiomeshcom.webapi import (
    AUTH_HMAC,
    AUTH_LEGACY,
    MeshComWebClient,
    MHeardEntry,
    WebApiError,
    WebAuthError,
    WebConnectionError,
    WebDowngradeError,
    WebThrottledError,
    parse_info_page,
    parse_mheard_page,
)
from tests.lib.mheard_html import Card, card, page
from tests.lib.node_pages_html import position_page, rxlog_page

PASSWORD = "Secret-Web-19chars"


@dataclass
class FakeNode:
    """Behaves like the firmware (web_functions.cpp, web_auth.cpp).

    ``legacy=False``: dev firmware with WEB-AUTH-01 (nonce + HMAC, cookie).
    ``legacy=True``: release 4.40a (``/?nodepassword=``, trusts the client IP).
    """

    password: str | None = PASSWORD
    params: dict[str, str] = field(
        default_factory=lambda: {
            "nomsgall": "off",
            "setgrc": "262;26298;0;0;0;0;",
            "setcall": "QX1YZ-12",
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
    legacy: bool = False
    ip_trusted: bool = False
    plaintext_seen: list[str] = field(default_factory=list)
    #: Battery cell of the info page, as the firmware prints it.
    battery: str = "4.012V (96%) max 4.240V"
    #: Stations on the MHeard page.
    mheard: list[Card] = field(default_factory=lambda: [Card("QR1ABC-12")])
    #: ``/austatus`` JSON; None: firmware without the built-in update (it
    #: answers with its info page).
    update: dict[str, Any] | None = None
    #: Update actions received with the X-MC header, and their answer.
    actions: list[str] = field(default_factory=list)
    action_ok: bool = True

    def info_page(self) -> str:
        """``/?page=info`` (sub_page_info in web_functions.cpp), padded past 4 KiB."""
        return (
            '<div id="content_title"><h1 class="font-bold">Node Information</h1></div>'
            '<table class="table mw-600"><tr><td>Firmware</td><td>Meshcom 4.40a<br>'
            "(build: Nov  1 2026 / 10:00:00)<br>(flash-version 1)</td></tr>\n"
            "<tr><td>Call</td><td>QX1YZ-12</td></tr>\n"
            f"<tr><td>Battery</td><td>{self.battery}</td></tr>\n" + "z" * 6000
        )

    def authorised(self, request: web.Request) -> bool:
        if self.password is None:
            return True
        if self.legacy:
            return self.ip_trusted
        cookie = request.headers.get("Cookie", "")
        return cookie.startswith("mcs=") and cookie[4:] in self.sessions

    async def root(self, request: web.Request) -> web.Response:
        self.requests.append(request.path_qs)
        self.headers_ok &= request.headers.get("X-MC") == "1"
        query = request.query_string
        if self.legacy:
            return self.root_legacy(request)
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

    async def dispatch(self, request: web.Request) -> web.Response:
        """``/`` serves the info page next to the login endpoints."""
        if request.query_string == "page=info":
            self.requests.append(request.path_qs)
            return self.page_info(request)
        if request.query_string in ("page=position", "page=rxlog"):
            self.requests.append(request.path_qs)
            if not self.authorised(request):
                return web.Response(text="<h1>Login</h1><form>password</form>")
            body = position_page() if request.query_string == "page=position" else rxlog_page()
            return web.Response(text=body)
        if request.query_string == "page=mheard":
            self.requests.append(request.path_qs)
            if not self.authorised(request):
                # The firmware answers a page request with its login page.
                return web.Response(text="<h1>Login</h1><form>password</form>")
            return web.Response(text=page(self.mheard))
        return await self.root(request)

    def page_info(self, request: web.Request) -> web.Response:
        if not self.authorised(request):
            return web.Response(status=401, text="Unauthorized")
        return web.Response(text=self.info_page())

    def root_legacy(self, request: web.Request) -> web.Response:
        """4.40a: 200 with a big HTML page for the login, 401 for unknown paths."""
        raw = request.raw_path.partition("?")[2]
        if raw.startswith("nodepassword="):
            # The node percent-decodes the rest of the request line.
            value = request.query.get("nodepassword", "")
            if value == "":
                self.ip_trusted = False
            else:
                self.plaintext_seen.append(value)
                if value == self.password:
                    self.ip_trusted = True
            return web.Response(text="<html>" + "x" * 6000)
        if self.password is not None and not self.ip_trusted:
            return web.Response(status=401, text="Unauthorized")
        return web.Response(text="<html>" + "y" * 6000)

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

    async def austatus(self, request: web.Request) -> web.Response:
        self.requests.append(request.path_qs)
        if not self.authorised(request):
            return web.Response(status=401, text="Unauthorized")
        if self.update is None:
            return web.Response(text=self.info_page())
        return web.json_response(self.update)

    async def callfunction(self, request: web.Request) -> web.Response:
        self.requests.append(request.path_qs)
        if not self.authorised(request):
            return web.Response(status=401, text="Unauthorized")
        name = request.query_string
        if self.mode == "server_error":
            return web.Response(status=500)
        if request.headers.get("X-MC") != "1":
            return web.json_response({"ok": False, "err": "forbidden"}, status=403)
        self.actions.append(name)
        if self.update is None or not self.action_ok:
            return web.json_response({name: "failed"}, status=422)
        return web.json_response({name: "ok"})

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
    app.router.add_get("/", node.dispatch)
    app.router.add_get("/getparam/", node.getparam)
    app.router.add_get("/setparam/", node.setparam)
    app.router.add_get("/austatus", node.austatus)
    app.router.add_get("/callfunction/", node.callfunction)
    test_server = TestServer(app)
    await test_server.start_server()
    yield test_server
    await test_server.close()


@pytest.fixture
async def session() -> AsyncGenerator[aiohttp.ClientSession]:
    async with aiohttp.ClientSession() as client_session:
        yield client_session


def client(
    session: aiohttp.ClientSession,
    server: TestServer,
    password: str | None = PASSWORD,
    *,
    allow_legacy: bool = True,
) -> MeshComWebClient:
    return MeshComWebClient(
        session,
        f"{server.host}:{server.port}",
        password,
        allow_legacy=allow_legacy,
        timeout=5,
    )


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
        ("bad_nonce", WebAuthError),
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


# --- firmware 4.40a (legacy login) ------------------------------------------


async def test_hmac_preferred(
    session: aiohttp.ClientSession, server: TestServer, node: FakeNode
) -> None:
    """A node with nonce login is never sent the plain-text password."""
    web_client = client(session, server)
    await web_client.get_param("nomsgall")
    assert web_client.auth_method == AUTH_HMAC
    assert not any("nodepassword" in r for r in node.requests)


async def test_legacy_login_read_logout(
    session: aiohttp.ClientSession, server: TestServer, node: FakeNode
) -> None:
    """4.40a: login, request, and the IP trust is ended right away."""
    node.legacy = True
    web_client = client(session, server)
    assert await web_client.get_status() == (False, ["262", "26298"])
    assert web_client.auth_method == AUTH_LEGACY
    assert node.ip_trusted is False
    assert node.requests[0] == "/?loginnonce"
    assert node.requests[-1] == "/?nodepassword="
    assert (
        sum(r.startswith("/?nodepassword=") and r != "/?nodepassword=" for r in node.requests) == 1
    )


@pytest.mark.parametrize("password", ["a b&c=d/e%f+g", "\u00e4\u00f6\u00fc-#?"])
async def test_legacy_password_encoding(
    session: aiohttp.ClientSession, server: TestServer, node: FakeNode, password: str
) -> None:
    """Special characters arrive at the node unchanged."""
    node.legacy = True
    node.password = password
    assert await client(session, server, password).get_param("nomsgall") == "off"
    assert node.plaintext_seen == [password]


async def test_legacy_wrong_password(
    session: aiohttp.ClientSession, server: TestServer, node: FakeNode
) -> None:
    """The login answer is 200 either way; the next request reveals it."""
    node.legacy = True
    with pytest.raises(WebAuthError):
        await client(session, server, "wrong").get_param("nomsgall")
    assert node.requests[-1] == "/?nodepassword="


async def test_legacy_set_param(
    session: aiohttp.ClientSession, server: TestServer, node: FakeNode
) -> None:
    node.legacy = True
    assert await client(session, server).set_param("nomsgall", "on") == "on"
    assert node.params["nomsgall"] == "on"
    assert node.ip_trusted is False


async def test_no_downgrade(
    session: aiohttp.ClientSession, server: TestServer, node: FakeNode
) -> None:
    """Pinned to the secure login: the plain-text password is never sent."""
    node.legacy = True
    web_client = client(session, server, allow_legacy=False)
    with pytest.raises(WebDowngradeError):
        await web_client.get_param("nomsgall")
    assert node.plaintext_seen == []
    assert not any("nodepassword" in r for r in node.requests)
    assert web_client.auth_method is None


async def test_legacy_open_node(
    session: aiohttp.ClientSession, server: TestServer, node: FakeNode
) -> None:
    """4.40a without web password: no login at all."""
    node.legacy = True
    node.password = None
    web_client = client(session, server, None)
    assert await web_client.is_open() is True
    assert await web_client.get_param("nomsgall") == "off"
    assert not any("nodepassword" in r or "login" in r for r in node.requests)


# --- info page: firmware and battery voltage --------------------------------------


async def test_overview_reads_info_page(
    session: aiohttp.ClientSession, server: TestServer, node: FakeNode
) -> None:
    """Settings, firmware and voltage come from one login session."""
    status = await client(session, server).get_overview()
    assert (status.no_msg_all, status.groups, status.firmware, status.battery_voltage) == (
        False,
        ["262", "26298"],
        "4.40a",
        4.012,
    )
    assert status.mheard is not None
    assert [e.callsign for e in status.mheard] == ["QR1ABC-12"]
    assert sum(r.startswith("/?login=") for r in node.requests) == 1
    assert "/?page=info" in node.requests
    assert "/?page=mheard" in node.requests


async def test_overview_legacy_and_usb(
    session: aiohttp.ClientSession, server: TestServer, node: FakeNode
) -> None:
    """4.40a login; a node on USB has no battery voltage."""
    node.legacy = True
    node.battery = "USB (no battery)"
    status = await client(session, server).get_overview()
    assert (status.firmware, status.battery_voltage) == ("4.40a", None)
    assert node.ip_trusted is False


async def test_overview_without_info_page(
    session: aiohttp.ClientSession, server: TestServer, node: FakeNode
) -> None:
    """If the page is missing, the settings are still read."""
    original = node.info_page
    node.info_page = lambda: "<html>other firmware</html>"  # type: ignore[method-assign]
    status = await client(session, server).get_overview()
    assert (status.no_msg_all, status.groups, status.firmware, status.battery_voltage) == (
        False,
        ["262", "26298"],
        None,
        None,
    )
    node.info_page = original  # type: ignore[method-assign]


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (
            "<tr><td>Firmware</td><td>Meshcom 4.40a<br>(build)</td></tr>"
            "<tr><td>Battery</td><td>3.912V (80%) max 4.2V</td></tr>",
            ("4.40a", 3.912),
        ),
        ("<td>Firmware</td><td>Meshcom 4.34 <br>", ("4.34", None)),
        ("<td>Battery</td><td>USB (no battery)</td>", (None, None)),
        ("<td>Battery</td><td>0.000V (0%)</td>", (None, None)),
        ("<td>Firmware</td><td>Meshcom <script>alert(1)</script><br>", (None, None)),
        ("<td>Battery</td><td>4.2V (90%)</td>", (None, None)),
        ("", (None, None)),
    ],
)
def test_parse_info_page(body: str, expected: tuple[str | None, float | None]) -> None:
    """Only the fixed shapes of the firmware are accepted."""
    assert parse_info_page(body) == expected


# --- MHeard page -------------------------------------------------------------------


def test_parse_mheard_page() -> None:
    """Every field of a card, as the firmware prints it."""
    body = page(
        [
            Card(
                "QR1ABC-12",
                age_min=0,
                plt="@",
                hw="TBEAM_AXP2101",
                rssi=-116,
                snr=-8,
                lat=50.123,
                lon=8.456,
                alt=491,
                hm_snr=-11,
                role="R",
                ex=0,
                nb=7,
                ncnt=6,
            ),
            Card(
                "QB0RLY-12",
                age_min=4,
                plt="!",
                hw="RAK4631",
                fw="-",
                rssi=None,
                snr=None,
                dist=None,
                lat=None,
                lon=None,
                alt=None,
                hm_snr=None,
                role="S",
                ex=1,
                nb=1,
                ncnt=1,
                gw=True,
            ),
            Card("QS9XYZ-1", age_min=3, plt=":", hw="no info", fw="v4.35", lat=-33.5, lon=-70.25),
        ]
    )
    assert parse_mheard_page(body) == [
        MHeardEntry(
            callsign="QR1ABC-12",
            age_minutes=0,
            last_frame="heartbeat",
            hardware="TBEAM_AXP2101",
            firmware="4.40a",
            rssi=-116,
            snr=-8,
            latitude=50.123,
            longitude=8.456,
            altitude=491,
            hears_me_snr=-11,
            relay_role="redundant",
            only_it_hears=0,
            it_hears=7,
            neighbours=6,
            gateway=False,
        ),
        MHeardEntry(
            callsign="QB0RLY-12",
            age_minutes=4,
            last_frame="position",
            hardware="RAK4631",
            firmware=None,
            rssi=None,
            snr=None,
            latitude=None,
            longitude=None,
            altitude=None,
            hears_me_snr=None,
            relay_role="super",
            only_it_hears=1,
            it_hears=1,
            neighbours=1,
            gateway=True,
        ),
        MHeardEntry(
            callsign="QS9XYZ-1",
            age_minutes=3,
            last_frame="text",
            hardware=None,
            firmware="4.35",
            rssi=-110,
            snr=-8,
            latitude=-33.5,
            longitude=-70.25,
            altitude=491,
            hears_me_snr=-11,
            relay_role="redundant",
            only_it_hears=0,
            it_hears=7,
            neighbours=6,
            gateway=False,
        ),
    ]


def test_parse_mheard_page_empty_and_foreign() -> None:
    """No stations is an empty list; another page (login) is None."""
    assert parse_mheard_page(page([])) == []
    assert parse_mheard_page("<h1>Login</h1>") is None
    assert parse_mheard_page("") is None


@pytest.mark.parametrize(
    "bad",
    [
        Card("<script>alert(1)</script>"),  # not a callsign
        Card("QR1ABC-12", age_min=99999),  # age out of range
        Card("Q&lt;b&gt;-1"),  # escaped markup is no callsign either
    ],
)
def test_parse_mheard_page_rejects_cards(bad: Card) -> None:
    """A card without a valid callsign or age is skipped; the others stay."""
    entries = parse_mheard_page(page([bad, Card("QB0RLY-12")]))
    assert entries is not None
    assert [e.callsign for e in entries] == ["QB0RLY-12"]


def test_parse_mheard_page_field_values_checked() -> None:
    """Odd values become None instead of reaching Home Assistant."""
    entries = parse_mheard_page(
        page([Card("QR1ABC-12", hw="<b>x</b>", fw="v9.9", rssi=-999, snr=99, lat=95.0, alt=123456)])
    )
    assert entries is not None
    (entry,) = entries
    assert (entry.hardware, entry.firmware, entry.rssi, entry.snr) == (None, None, None, None)
    assert (entry.latitude, entry.longitude, entry.altitude) == (None, None, None)


def test_parse_mheard_page_cut_and_duplicate() -> None:
    """A card cut off at the end is ignored, a repeated callsign counted once."""
    full = page([Card("QR1ABC-12"), Card("QR1ABC-12", age_min=9), Card("QB0RLY-12")])
    cut = full[: full.rindex("Gateway")]
    entries = parse_mheard_page(cut)
    assert entries is not None
    assert [(e.callsign, e.age_minutes) for e in entries] == [("QR1ABC-12", 0)]


def test_parse_mheard_page_entry_limit() -> None:
    """At most 128 stations are taken from one page."""
    cards = [Card(f"QA{i // 26 % 10}{chr(65 + i % 26)}{chr(65 + i // 260)}-1") for i in range(150)]
    entries = parse_mheard_page(page(cards))
    assert entries is not None
    assert len(entries) == 128


async def test_overview_large_mheard_page(
    session: aiohttp.ClientSession, server: TestServer, node: FakeNode
) -> None:
    """A long list arrives completely (several network reads), the settings still work."""
    node.mheard = [Card(f"QA{i % 10}{chr(65 + i // 10)}-12") for i in range(100)]
    status = await client(session, server).get_overview()
    assert status.mheard is not None
    assert len(status.mheard) == 100
    assert len(page(node.mheard)) > 64 * 1024


def test_mheard_card_helper_matches_shape() -> None:
    """The test renderer keeps the firmware's field order (guard for the fixture)."""
    html = card(Card("QR1ABC-12"))
    assert (
        html.index("Last frame")
        < html.index("Altitude")
        < html.index("Last heard")
        < html.index("Gateway")
    )


async def test_overview_node_pages(
    session: aiohttp.ClientSession, server: TestServer, node: FakeNode
) -> None:
    """Position page always, the RX log page only when asked for (it costs node RAM)."""
    status = await client(session, server).get_overview()
    assert status.gps is not None
    assert status.gps.satellites == 10
    assert status.radio is None
    assert "/?page=rxlog" not in node.requests
    status = await client(session, server).get_overview(radio_stats=True)
    assert status.radio is not None
    assert status.radio.rx_percent == 11.4
    assert "/?page=rxlog" in node.requests
    assert status.info is not None


UPDATE_STATUS: dict[str, Any] = {
    "st": "ok",
    "job": "check",
    "run": "v4.40a.11.07",
    "avail": "v4.40a.11.20",
    "newer": 1,
    "inst": 1,
    "staged": "",
    "err": "",
    "pct": 0,
    "phone": 0,
    "guard": 0,
    "sbok": 1,
    "mode": "notify",
    "chan": "prod",
    "etaS": 0,
    "ifree": 120000,
    "iblk": 60000,
    "sbwhy": "ok",
    "up": 3600,
    "img": "0123abcd",
}


async def test_overview_update_status(
    session: aiohttp.ClientSession, server: TestServer, node: FakeNode
) -> None:
    """The update state comes with the poll; older firmware has none."""
    status = await client(session, server).get_overview()
    assert status.update is None
    assert "/austatus" in node.requests
    node.update = dict(UPDATE_STATUS)
    status = await client(session, server).get_overview()
    assert status.update is not None
    assert status.update.running == "v4.40a.11.07"
    assert status.update.available == "v4.40a.11.20"
    assert status.update.newer
    assert status.update.staged is None
    assert status.update.error is None
    assert node.headers_ok


async def test_update_actions(
    session: aiohttp.ClientSession, server: TestServer, node: FakeNode
) -> None:
    """Download and install are sent with the X-MC header; only these two."""
    web = client(session, server)
    node.update = dict(UPDATE_STATUS)
    assert await web.update_action("updinstall")
    assert await web.update_action("updapply")
    assert node.actions == ["updinstall", "updapply"]
    node.action_ok = False
    assert not await web.update_action("updinstall")
    with pytest.raises(ValueError, match="not allowed"):
        await web.update_action("otaupdate")
    status = await web.get_update_status()
    assert status is not None
    assert status.running == "v4.40a.11.07"
    node.update = None
    assert await web.get_update_status() is None


async def test_update_needs_login(session: aiohttp.ClientSession, server: TestServer) -> None:
    """Without the password the node answers 401."""
    web = client(session, server, password=None)
    with pytest.raises(WebAuthError):
        await web.get_update_status()
    with pytest.raises(WebAuthError):
        await web.update_action("updinstall")


async def test_update_action_unexpected_status(
    session: aiohttp.ClientSession, server: TestServer, node: FakeNode
) -> None:
    """Any other answer than 200 or 422 is a connection error."""
    node.update = dict(UPDATE_STATUS)
    node.mode = "server_error"
    with pytest.raises(WebConnectionError):
        await client(session, server).update_action("updinstall")
