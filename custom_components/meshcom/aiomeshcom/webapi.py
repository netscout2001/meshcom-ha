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
import json
import re
from dataclasses import dataclass
from typing import Any, Final
from urllib.parse import quote

import aiohttp
from yarl import URL

from .const import SECRET_WEB_PARAMETERS
from .errors import MeshComError

#: Parameters the client may read.
READABLE_PARAMETERS: Final = frozenset({"nomsgall", "setgrc", "setcall"})
#: Parameters the client may write, with their allowed values.
WRITABLE_PARAMETERS: Final = {"nomsgall": frozenset({"on", "off"})}

_MAX_RESPONSE_BYTES: Final = 4096
#: HTML page with firmware and battery; both rows are in its first kilobyte.
INFO_PAGE: Final = "/?page=info"
_INFO_FIRMWARE_RE: Final = re.compile(r"<td>Firmware</td><td>Meshcom (\d\.\d{2}) *([a-z]{0,2})<br>")
_INFO_BATTERY_RE: Final = re.compile(r"<td>Battery</td><td>(\d{1,2}\.\d{3})V \(\d{1,3}%\)")
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
        self, path: str, token: str | None = None, *, truncate: bool = False
    ) -> tuple[int, str, str | None]:
        """GET ``path``; returns status, body and the session token if one was set.

        ``path`` must already be percent-encoded. With ``truncate`` an
        oversized body (an HTML page) is cut instead of rejected.
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
                body = await response.content.read(_MAX_RESPONSE_BYTES + 1)
                if len(body) > _MAX_RESPONSE_BYTES:
                    if not truncate:
                        raise WebConnectionError("response too large")
                    body = body[:_MAX_RESPONSE_BYTES]
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
        self, paths: list[str], *, pages: frozenset[str] = frozenset()
    ) -> list[tuple[int, str]]:
        """GET several paths in one login session; ``pages`` are HTML pages (cut, not rejected)."""
        answers: list[tuple[int, str]] = []
        async with self._lock:
            session = await self._login()
            token = session.token if session is not None else None
            try:
                for path in paths:
                    status, body, _ = await self._get(path, token, truncate=path in pages)
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

    async def get_overview(self) -> NodeStatus:
        """Settings plus firmware and battery voltage, with a single login.

        Firmware and voltage are only on the node's info page (HTML). They
        are taken from it with fixed patterns; if the page looks different,
        they stay unknown and the settings are still returned.
        """
        answers = await self._fetch(
            ["/getparam/?nomsgall", "/getparam/?setgrc", INFO_PAGE], pages=frozenset({INFO_PAGE})
        )
        no_msg_all = _value("nomsgall", *answers[0])
        groups = parse_groups(_value("setgrc", *answers[1]))
        info_status, info_body = answers[2]
        firmware, voltage = parse_info_page(info_body) if info_status == 200 else (None, None)
        return NodeStatus(no_msg_all == "on", groups, firmware, voltage)

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


def parse_groups(raw: str) -> list[str]:
    """``"262;26298;0;0;0;0;"`` -> ``["262", "26298"]``."""
    groups = [part for part in raw.split(";") if part and part != "0"]
    if not all(part.isdigit() and len(part) <= 5 for part in groups):
        raise WebConnectionError("unexpected group list")
    return groups


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


def _json_field(body: str, key: str) -> str | None:
    try:
        value = _parse_json(body).get(key)
    except WebConnectionError:
        return None
    return value if isinstance(value, str) else None
