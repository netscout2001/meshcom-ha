"""Client for the MeshCom node web API (firmware 4.40a and later).

Security properties (security concept C-04, C-10, C-16, F-05, F-06):

* Login only by nonce and HMAC-SHA256 (``/?loginnonce``, ``/?login=``);
  the password itself never travels. The legacy plain-text login is not
  supported.
* Every operation logs in, does its request and logs out again, so a
  session cookie is valid only for seconds (the node has no TLS).
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
from typing import Any, Final

import aiohttp

from .const import SECRET_WEB_PARAMETERS
from .errors import MeshComError

#: Parameters the client may read.
READABLE_PARAMETERS: Final = frozenset({"nomsgall", "setgrc", "setcall"})
#: Parameters the client may write, with their allowed values.
WRITABLE_PARAMETERS: Final = {"nomsgall": frozenset({"on", "off"})}

_MAX_RESPONSE_BYTES: Final = 4096
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
        timeout: float = 10.0,
    ) -> None:
        self._session = session
        self._base = f"http://{host}"
        self._password = password or None
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._lock = asyncio.Lock()

    # --- transport -------------------------------------------------------------

    async def _get(self, path: str, token: str | None = None) -> tuple[int, str, str | None]:
        """GET ``path``; returns status, body and the session token if one was set."""
        headers = dict(_HEADERS)
        if token is not None:
            headers["Cookie"] = f"mcs={token}"
        try:
            async with self._session.get(
                self._base + path,
                headers=headers,
                timeout=self._timeout,
                allow_redirects=False,
            ) as response:
                body = await response.content.read(_MAX_RESPONSE_BYTES + 1)
                if len(body) > _MAX_RESPONSE_BYTES:
                    raise WebConnectionError("response too large")
                new_token = None
                for cookie in response.headers.getall("Set-Cookie", []):
                    match = _TOKEN_RE.match(cookie)
                    if match is not None:
                        new_token = match.group(1)
                return response.status, body.decode("utf-8", "replace"), new_token
        except (aiohttp.ClientError, TimeoutError) as err:
            raise WebConnectionError(type(err).__name__) from err

    async def _login(self) -> str | None:
        if self._password is None:
            return None
        status, body, _ = await self._get("/?loginnonce")
        nonce = body.strip()
        if status == 403:
            raise WebThrottledError("login throttled")
        if status != 200 or _NONCE_RE.fullmatch(nonce) is None:
            raise WebConnectionError("no login nonce")
        # The node computes HMAC-SHA256(key=password, msg=the 32 hex characters).
        mac = hmac.new(self._password.encode(), nonce.encode(), hashlib.sha256).hexdigest()
        status, body, token = await self._get(f"/?login={nonce}.{mac}")
        if status == 200 and token is not None:
            return token
        error = _json_field(body, "err")
        if error == "throttled":
            raise WebThrottledError("login throttled")
        if status == 403:
            raise WebAuthError("login rejected")  # no node text in logs
        raise WebConnectionError("unexpected login answer")

    async def _logout(self, token: str | None) -> None:
        if token is None:
            return
        # The session expires on its own; a failed logout is not an error.
        with contextlib.suppress(WebConnectionError):
            await self._get("/?logout", token)

    async def _request(self, path: str, name: str) -> str:
        return (await self._requests([(path, name)]))[name]

    async def _requests(self, requests: list[tuple[str, str]]) -> dict[str, str]:
        """Several requests in one login session."""
        answers: list[tuple[str, int, str]] = []
        async with self._lock:
            token = await self._login()
            try:
                for path, name in requests:
                    status, body, _ = await self._get(path, token)
                    answers.append((name, status, body))
            finally:
                await self._logout(token)
        return {name: _value(name, status, body) for name, status, body in answers}

    async def get_params(self, names: list[str]) -> dict[str, str]:
        """Read several allowlisted parameters with a single login."""
        for name in names:
            if name not in READABLE_PARAMETERS:
                raise ValueError(f"parameter not allowed: {name}")
        return await self._requests([(f"/getparam/?{name}", name) for name in names])

    async def get_status(self) -> tuple[bool, list[str]]:
        """``No MSG All`` switch and listening groups, with a single login."""
        values = await self.get_params(["nomsgall", "setgrc"])
        return values["nomsgall"] == "on", parse_groups(values["setgrc"])

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
