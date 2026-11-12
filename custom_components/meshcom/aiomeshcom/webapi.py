"""Client for the MeshCom node web API (firmware 4.40a and later).

Security properties (security concept C-04, C-10, C-16, F-05, F-06):

* Preferred login: nonce and HMAC-SHA256 (``/?loginnonce``, ``/?login=``,
  firmware with WEB-AUTH-01); the password itself never travels.
* Firmware 4.40a only knows ``/?nodepassword=<password>`` (plain text in
  the URL), after which the node trusts the client's *IP address* for 4 h.
  It is used only when the node offers no nonce login and the caller allows
  it (``allow_legacy``). Once a node has used the secure login, the caller
  pins it and never falls back again (no downgrade).
* Every operation logs in, does its request and logs out again, so a
  session (cookie or IP trust) is valid only for seconds (the node has no
  TLS).
* The session cookie is kept in memory for one operation and sent
  explicitly; it never lands in a shared cookie jar.
* Only allowlisted parameters can be read or written. Parameters that
  return secrets (WLAN password, ...) and ``/config.json`` are unreachable.
* One request at a time per node; the node runs a single-threaded server.
* Responses are size-limited and parsed strictly.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import hmac
import html
import json
import re
from dataclasses import dataclass
from typing import Any, Final
from urllib.parse import quote

import aiohttp
from yarl import URL

from .callsign import is_callsign
from .const import SECRET_WEB_PARAMETERS
from .errors import MeshComError
from .webpages import (
    POSITION_PAGE,
    RXLOG_PAGE,
    UPDATE_STATUS_PATH,
    GpsInfo,
    NodeInfo,
    RadioStats,
    UpdateStatus,
    parse_node_info,
    parse_position_page,
    parse_rxlog_page,
    parse_update_status,
)

#: Parameters the client may read.
READABLE_PARAMETERS: Final = frozenset({"nomsgall", "setgrc", "setcall"})
#: Parameters the client may write, with their allowed values.
WRITABLE_PARAMETERS: Final = {"nomsgall": frozenset({"on", "off"})}

_MAX_RESPONSE_BYTES: Final = 4096
#: HTML page with firmware and battery; both rows are in its first kilobyte.
INFO_PAGE: Final = "/?page=info"
_INFO_FIRMWARE_RE: Final = re.compile(r"<td>Firmware</td><td>Meshcom (\d\.\d{2}) *([a-z]{0,2})<br>")
_INFO_BATTERY_RE: Final = re.compile(r"<td>Battery</td><td>(\d{1,2}\.\d{3})V \(\d{1,3}%\)")
#: HTML page of the stations the node heard directly in the last 3 hours
#: (firmware 4.40a). One card of about 1.5 kB per station; the node lists up
#: to 128. A longer page is cut; the cut card is ignored.
MHEARD_PAGE: Final = "/?page=mheard"
_MHEARD_MAX_BYTES: Final = 256 * 1024
_MHEARD_TITLE: Final = "MHeard Information"
#: The info page is about 6 kB; the values at its end must not be cut off.
_INFO_MAX_BYTES: Final = 32 * 1024
#: The queue panel is at the top of the RX log page; the log lines below it
#: are not needed.
_RXLOG_MAX_BYTES: Final = 8 * 1024
_MHEARD_MAX_ENTRIES: Final = 128
#: The update status is a JSON object of about 400 bytes.
_UPDATE_MAX_BYTES: Final = 2048
#: Firmware update actions of the node (they need the ``X-MC: 1`` header).
UPDATE_DOWNLOAD: Final = "updinstall"
UPDATE_INSTALL: Final = "updapply"
_UPDATE_ACTIONS: Final = frozenset({UPDATE_DOWNLOAD, UPDATE_INSTALL})
_MHEARD_CARD_RE: Final = re.compile(
    r'<label class="cardlabel"><a href="https://aprs\.fi/\?call=[^"]{1,40}" target="_blank">'
    r"([^<]{1,40})</a>"
)
_MHEARD_FIELD_RE: Final = re.compile(
    r'<div><span class="font-bold">([A-Za-z /()]{1,20}):</span><br>'
    r"<span[^>]{0,120}>([^<]{0,40})</span></div>"
)
#: Login method used by the node.
AUTH_HMAC: Final = "hmac"
AUTH_LEGACY: Final = "legacy"
_NONCE_RE: Final = re.compile(r"[0-9a-f]{32}")
_TOKEN_RE: Final = re.compile(r"mcs=([0-9a-f]{32})")
#: Sent on every request; required by nodes built with MC_WEB_GUARD=1.
_HEADERS: Final = {"X-MC": "1"}

if READABLE_PARAMETERS & SECRET_WEB_PARAMETERS:  # pragma: no cover - guard against edits
    raise RuntimeError("a secret parameter must never be readable")


class WebApiError(MeshComError):
    """The web API request failed."""


class WebConnectionError(WebApiError):
    """The node could not be reached or answered unexpectedly."""


class WebAuthError(WebApiError):
    """The node rejected the login or requires one."""


class WebDowngradeError(WebApiError):
    """The node no longer offers the secure login it used before."""


@dataclass(slots=True)
class _Session:
    method: str
    token: str | None = None


class WebThrottledError(WebApiError):
    """The node blocks logins for a minute after five failed attempts."""


class MeshComWebClient:
    """Talks to one node's web API."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        password: str | None,
        *,
        allow_legacy: bool = True,
        timeout: float = 10.0,
    ) -> None:
        self._session = session
        self._base = f"http://{host}"
        self._password = password or None
        self.allow_legacy = allow_legacy
        #: Login method of the last successful login, or None.
        self.auth_method: str | None = None
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._lock = asyncio.Lock()

    # --- transport -------------------------------------------------------------

    async def _get(
        self,
        path: str,
        token: str | None = None,
        *,
        truncate: bool = False,
        limit: int = _MAX_RESPONSE_BYTES,
    ) -> tuple[int, str, str | None]:
        """GET ``path``; returns status, body and the session token if one was set.

        ``path`` must already be percent-encoded. With ``truncate`` an
        oversized body (an HTML page) is cut instead of rejected. ``limit`` is
        the largest body read.
        """
        headers = dict(_HEADERS)
        if token is not None:
            headers["Cookie"] = f"mcs={token}"
        try:
            async with self._session.get(
                URL(self._base + path, encoded=True),
                headers=headers,
                timeout=self._timeout,
                allow_redirects=False,
            ) as response:
                body = await _read_body(response.content, limit + 1)
                if len(body) > limit:
                    if not truncate:
                        raise WebConnectionError("response too large")
                    body = body[:limit]
                new_token = None
                for cookie in response.headers.getall("Set-Cookie", []):
                    match = _TOKEN_RE.match(cookie)
                    if match is not None:
                        new_token = match.group(1)
                return response.status, body.decode("utf-8", "replace"), new_token
        except (aiohttp.ClientError, TimeoutError) as err:
            raise WebConnectionError(type(err).__name__) from err

    async def _login(self) -> _Session | None:
        password = self._password
        if password is None:
            return None
        # 4.40a answers 401 (or an HTML page) here; newer firmware a nonce.
        status, body, _ = await self._get("/?loginnonce", truncate=True)
        nonce = body.strip()
        if status == 403:
            raise WebThrottledError("login throttled")
        if status == 200 and _NONCE_RE.fullmatch(nonce) is not None:
            session = _Session(AUTH_HMAC, await self._login_hmac(password, nonce))
        elif self.allow_legacy:
            session = await self._login_legacy(password)
        else:
            raise WebDowngradeError("secure login not offered")
        self.auth_method = session.method
        return session

    async def _login_legacy(self, password: str) -> _Session:
        """Firmware 4.40a: plain-text password; the node then trusts our IP.

        The answer is always 200 with an HTML page, also for a wrong
        password; the following request tells (401 = rejected).
        """
        await self._get("/?nodepassword=" + quote(password, safe=""), truncate=True)
        return _Session(AUTH_LEGACY)

    async def _login_hmac(self, password: str, nonce: str) -> str:
        # The node computes HMAC-SHA256(key=password, msg=the 32 hex characters).
        mac = hmac.new(password.encode(), nonce.encode(), hashlib.sha256).hexdigest()
        status, body, token = await self._get(f"/?login={nonce}.{mac}")
        if status == 200 and token is not None:
            return token
        error = _json_field(body, "err")
        if error == "throttled":
            raise WebThrottledError("login throttled")
        if status == 403:
            raise WebAuthError("login rejected")  # no node text in logs
        raise WebConnectionError("unexpected login answer")

    async def _logout(self, session: _Session | None) -> None:
        if session is None:
            return
        # The session expires on its own; a failed logout is not an error.
        with contextlib.suppress(WebConnectionError):
            if session.method == AUTH_HMAC:
                await self._get("/?logout", session.token)
            else:
                # An empty password ends the node's trust in our IP address.
                await self._get("/?nodepassword=", truncate=True)

    async def _request(self, path: str, name: str) -> str:
        return (await self._requests([(path, name)]))[name]

    async def _requests(self, requests: list[tuple[str, str]]) -> dict[str, str]:
        """Several parameter requests in one login session."""
        answers = await self._fetch([path for path, _ in requests])
        return {
            name: _value(name, status, body)
            for (_, name), (status, body) in zip(requests, answers, strict=True)
        }

    async def _fetch(
        self,
        paths: list[str],
        *,
        pages: frozenset[str] = frozenset(),
        limits: dict[str, int] | None = None,
    ) -> list[tuple[int, str]]:
        """GET several paths in one login session.

        ``pages`` are HTML pages (cut, not rejected); ``limits`` raise the
        size limit for single paths.
        """
        answers: list[tuple[int, str]] = []
        async with self._lock:
            session = await self._login()
            token = session.token if session is not None else None
            try:
                for path in paths:
                    limit = (limits or {}).get(path, _MAX_RESPONSE_BYTES)
                    status, body, _ = await self._get(
                        path, token, truncate=path in pages, limit=limit
                    )
                    answers.append((status, body))
            finally:
                await self._logout(session)
        return answers

    async def get_params(self, names: list[str]) -> dict[str, str]:
        """Read several allowlisted parameters with a single login."""
        for name in names:
            if name not in READABLE_PARAMETERS:
                raise ValueError(f"parameter not allowed: {name}")
        return await self._requests([(f"/getparam/?{name}", name) for name in names])

    async def get_status(self) -> tuple[bool, list[str]]:
        """``No MSG All`` switch and listening groups, with a single login."""
        status = await self.get_overview()
        return status.no_msg_all, status.groups

    async def get_overview(self, *, radio_stats: bool = False) -> NodeStatus:
        """Settings and the values of the node's pages, with a single login.

        Firmware, voltage, the MHeard list and the other node values are
        only on HTML pages. They are taken from them with fixed patterns; if
        a page looks different, its values stay unknown and the settings are
        still returned. ``radio_stats`` also reads the RX log page (LoRa
        queue); its first request makes the node allocate the RX log buffer.
        """
        pages = [INFO_PAGE, MHEARD_PAGE, POSITION_PAGE]
        if radio_stats:
            pages.append(RXLOG_PAGE)
        # Firmware without the update route answers with its info page.
        pages.append(UPDATE_STATUS_PATH)
        answers = await self._fetch(
            ["/getparam/?nomsgall", "/getparam/?setgrc", *pages],
            pages=frozenset(pages),
            limits={
                INFO_PAGE: _INFO_MAX_BYTES,
                MHEARD_PAGE: _MHEARD_MAX_BYTES,
                RXLOG_PAGE: _RXLOG_MAX_BYTES,
                UPDATE_STATUS_PATH: _UPDATE_MAX_BYTES,
            },
        )
        no_msg_all = _value("nomsgall", *answers[0])
        groups = parse_groups(_value("setgrc", *answers[1]))
        bodies = {
            path: body if status == 200 else None
            for path, (status, body) in zip(pages, answers[2:], strict=True)
        }
        info_body = bodies[INFO_PAGE]
        firmware, voltage = parse_info_page(info_body) if info_body else (None, None)
        mheard_body = bodies[MHEARD_PAGE]
        position_body = bodies[POSITION_PAGE]
        rxlog_body = bodies.get(RXLOG_PAGE)
        update_body = bodies[UPDATE_STATUS_PATH]
        return NodeStatus(
            no_msg_all == "on",
            groups,
            firmware,
            voltage,
            parse_mheard_page(mheard_body) if mheard_body is not None else None,
            info=parse_node_info(info_body) if info_body else None,
            gps=parse_position_page(position_body) if position_body else None,
            radio=parse_rxlog_page(rxlog_body) if rxlog_body else None,
            update=_update_status(update_body) if update_body else None,
        )

    async def get_update_status(self) -> UpdateStatus | None:
        """State of the built-in firmware update; None if the node has none."""
        ((status, body),) = await self._fetch(
            [UPDATE_STATUS_PATH],
            pages=frozenset({UPDATE_STATUS_PATH}),
            limits={UPDATE_STATUS_PATH: _UPDATE_MAX_BYTES},
        )
        if status == 401:
            raise WebAuthError("login required")
        return _update_status(body) if status == 200 else None

    async def update_action(self, action: str) -> bool:
        """Start a firmware update step; True if the node accepted it.

        ``updinstall`` downloads the release the node found and stages it,
        ``updapply`` installs the staged image and restarts the node.
        """
        if action not in _UPDATE_ACTIONS:
            raise ValueError(f"update action not allowed: {action}")
        ((status, body),) = await self._fetch([f"/callfunction/?{action}"])
        if status == 401:
            raise WebAuthError("login required")
        if status not in (200, 422):
            raise WebConnectionError(f"HTTP {status}")
        return status == 200 and _json_field(body, action) == "ok"

    # --- public API ------------------------------------------------------------

    async def get_param(self, name: str) -> str:
        """Read an allowlisted parameter."""
        if name not in READABLE_PARAMETERS:
            raise ValueError(f"parameter not allowed: {name}")
        return await self._request(f"/getparam/?{name}", name)

    async def set_param(self, name: str, value: str) -> str:
        """Write an allowlisted parameter; returns the value the node now uses."""
        allowed = WRITABLE_PARAMETERS.get(name)
        if allowed is None or value not in allowed:
            raise ValueError(f"parameter or value not allowed: {name}")
        return await self._request(f"/setparam/?{name}={value}", name)

    async def get_groups(self) -> list[str]:
        """The node's listening groups."""
        return parse_groups(await self.get_param("setgrc"))

    async def is_open(self) -> bool:
        """True if the node answers without login, i.e. has no web password (F-01)."""
        async with self._lock:
            status, _, _ = await self._get("/getparam/?nomsgall")
        return status == 200


@dataclass(frozen=True, slots=True)
class NodeStatus:
    """What one poll of the web API returns."""

    no_msg_all: bool
    groups: list[str]
    #: e.g. "4.40a"; None if the info page could not be read.
    firmware: str | None = None
    #: Battery voltage in volts; None without battery or if unknown.
    battery_voltage: float | None = None
    #: Stations heard directly (MHeard page); None if the page was unreadable.
    mheard: list[MHeardEntry] | None = None
    #: Further values of the info page.
    info: NodeInfo | None = None
    #: GPS state of the position page.
    gps: GpsInfo | None = None
    #: LoRa queue and channel use (RX log page, only when enabled).
    radio: RadioStats | None = None
    #: Built-in firmware update; None if the firmware has none.
    update: UpdateStatus | None = None


@dataclass(frozen=True, slots=True)
class MHeardEntry:
    """One station of the node's MHeard page (heard directly, last 3 hours)."""

    callsign: str
    #: Minutes since the node last received the station directly.
    age_minutes: int
    #: "text", "position", "heartbeat" or None.
    last_frame: str | None = None
    hardware: str | None = None
    #: e.g. "4.40a".
    firmware: str | None = None
    rssi: int | None = None
    snr: int | None = None
    latitude: float | None = None
    longitude: float | None = None
    altitude: int | None = None
    #: SNR at which the station reports to hear the node; None: not reported.
    hears_me_snr: int | None = None
    #: "super", "needed", "redundant" or None.
    relay_role: str | None = None
    #: Stations only it hears (of the node's direct neighbours).
    only_it_hears: int | None = None
    #: Stations it hears, as far as the node knows.
    it_hears: int | None = None
    #: Neighbour count the station announces itself.
    neighbours: int | None = None
    gateway: bool | None = None


def parse_info_page(body: str) -> tuple[str | None, float | None]:
    """Firmware version and battery voltage from the node's info page.

    Firmware 4.40a prints ``<td>Firmware</td><td>Meshcom 4.40a<br>`` and
    ``<td>Battery</td><td>4.012V (96%)`` (``USB (no battery)`` without one).
    Only these fixed shapes are accepted; anything else gives None.
    """
    firmware = None
    if (match := _INFO_FIRMWARE_RE.search(body)) is not None:
        firmware = match.group(1) + match.group(2)
    voltage = None
    if (match := _INFO_BATTERY_RE.search(body)) is not None:
        value = float(match.group(1))
        if 0 < value < 10:
            voltage = value
    return firmware, voltage


_FRAMES: Final = {"Text message": "text", "Position": "position", "Heartbeat (HEY)": "heartbeat"}
_ROLES: Final = {"Super node": "super", "Needed": "needed", "Redundant": "redundant"}
_HARDWARE_RE: Final = re.compile(r"[A-Za-z0-9_+]{1,24}")
_FIRMWARE_RE: Final = re.compile(r"v(4\.\d{2}[a-z]?)")
_COORD_RE: Final = re.compile(r"([NSEW])(\d{1,3}\.\d{3})")


def _int(value: str | None, pattern: str, low: int, high: int) -> int | None:
    """An integer from ``value`` if it has the shape ``pattern`` (one group)."""
    if value is None or (match := re.fullmatch(pattern, value)) is None:
        return None
    number = int(match.group(1))
    return number if low <= number <= high else None


def _coordinate(value: str | None, positive: str, negative: str, limit: float) -> float | None:
    if value is None or (match := _COORD_RE.fullmatch(value)) is None:
        return None
    hemisphere, number = match.group(1), float(match.group(2))
    if hemisphere not in (positive, negative) or number > limit:
        return None
    return -number if hemisphere == negative else number


def _mheard_card(callsign: str, fields: dict[str, str]) -> MHeardEntry | None:
    age = _int(fields.get("Last heard"), r"(\d{1,4}) min ago", 0, 24 * 60)
    if age is None:
        return None
    hardware = fields.get("Hardware")
    firmware = _FIRMWARE_RE.fullmatch(fields.get("Firmware", ""))
    latitude = _coordinate(fields.get("Lat"), "N", "S", 90)
    longitude = _coordinate(fields.get("Lon"), "E", "W", 180)
    if latitude is None or longitude is None or (latitude == 0 and longitude == 0):
        latitude = longitude = None
    gateway = {"yes": True, "no": False}.get(fields.get("Gateway", ""))
    return MHeardEntry(
        callsign=callsign,
        age_minutes=age,
        last_frame=_FRAMES.get(fields.get("Last frame", "")),
        hardware=hardware
        if hardware and hardware != "no info" and _HARDWARE_RE.fullmatch(hardware)
        else None,
        firmware=firmware.group(1) if firmware else None,
        rssi=_int(fields.get("RSSI"), r"(-?\d{1,3}) dBm", -200, 50),
        snr=_int(fields.get("SNR (avg)"), r"(-?\d{1,2}) dB", -50, 50),
        latitude=latitude,
        longitude=longitude,
        altitude=_int(fields.get("Altitude"), r"(-?\d{1,5}) m", -500, 9999),
        hears_me_snr=_int(fields.get("Hears me"), r"yes, (-?\d{1,2}) dB", -50, 50),
        relay_role=_ROLES.get(fields.get("Relay role", "")),
        only_it_hears=_int(fields.get("Only it hears"), r"(\d{1,3}) stations?", 0, 999),
        it_hears=_int(fields.get("It hears"), r"(\d{1,3}) stations?", 0, 999),
        neighbours=_int(fields.get("It reports"), r"(\d{1,3}) neighbours?", 0, 999),
        gateway=gateway,
    )


def parse_mheard_page(body: str) -> list[MHeardEntry] | None:
    """Stations from the node's MHeard page (firmware 4.40a).

    Each station is a card: ``<label class="cardlabel"><a href="https://aprs.fi/?call=X"
    target="_blank">X</a> ...</label>`` followed by ``<div><span class="font-bold">Name:</span>
    <br><span>value</span></div>`` fields. Only these fixed shapes are read;
    a card without a valid callsign, without its age or cut off at the end
    (no "Gateway" field yet) is skipped. None if the page is not the MHeard
    page at all (e.g. the login page).
    """
    if _MHEARD_TITLE not in body:
        return None
    entries: list[MHeardEntry] = []
    seen: set[str] = set()
    starts = list(_MHEARD_CARD_RE.finditer(body))
    for index, match in enumerate(starts):
        end = starts[index + 1].start() if index + 1 < len(starts) else len(body)
        callsign = html.unescape(match.group(1)).strip().upper()
        if not is_callsign(callsign) or callsign in seen:
            continue
        fields = {
            name: html.unescape(value).strip()
            for name, value in _MHEARD_FIELD_RE.findall(body, match.end(), end)
        }
        if "Gateway" not in fields:
            continue
        if (entry := _mheard_card(callsign, fields)) is not None:
            seen.add(callsign)
            entries.append(entry)
            if len(entries) >= _MHEARD_MAX_ENTRIES:
                break
    return entries


def parse_groups(raw: str) -> list[str]:
    """``"262;26298;0;0;0;0;"`` -> ``["262", "26298"]``."""
    groups = [part for part in raw.split(";") if part and part != "0"]
    if not all(part.isdigit() and len(part) <= 5 for part in groups):
        raise WebConnectionError("unexpected group list")
    return groups


async def _read_body(content: aiohttp.StreamReader, limit: int) -> bytes:
    """Read at most ``limit`` bytes (``read(n)`` may return fewer)."""
    chunks: list[bytes] = []
    size = 0
    while size < limit:
        chunk = await content.read(limit - size)
        if not chunk:
            break
        chunks.append(chunk)
        size += len(chunk)
    return b"".join(chunks)


def _value(name: str, status: int, body: str) -> str:
    if status == 401:
        raise WebAuthError("login required")
    if status not in (200, 422):
        raise WebConnectionError(f"HTTP {status}")
    data = _parse_json(body)
    value = data.get(name)
    if not isinstance(value, str) or len(value) > 128:
        raise WebConnectionError("unexpected answer")
    if data.get("returncode") != 0:
        raise WebApiError(f"node refused {name}")
    return value


def _parse_json(body: str) -> dict[str, Any]:
    try:
        data = json.loads(body)
    except ValueError as err:
        raise WebConnectionError("invalid JSON") from err
    if not isinstance(data, dict):
        raise WebConnectionError("invalid JSON")
    return data


def _update_status(body: str) -> UpdateStatus | None:
    try:
        data = json.loads(body)
    except ValueError:
        return None
    return parse_update_status(data)


def _json_field(body: str, key: str) -> str | None:
    try:
        value = _parse_json(body).get(key)
    except WebConnectionError:
        return None
    return value if isinstance(value, str) else None
