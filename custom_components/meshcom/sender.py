"""Transmit gate for MeshCom.

Everything sent here goes out on amateur radio under the node's callsign.
Every path that transmits (service, button, chat panel) goes through
:func:`async_send_text`, which enforces in this order:

1. the per-node "Allow sending" switch (kill switch),
2. who may transmit: administrators, plus users released in the options
   (security concept C-02); calls without a user (automations, scripts
   started by the system) count as the owner's own configuration,
3. a rate limit for the whole Home Assistant instance (C-06, T3),
4. validation of destination and text by the protocol builder.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from homeassistant.core import Context, HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError, Unauthorized

from .aiomeshcom import InvalidOutgoingError, build_text_message
from .const import (
    CONF_SEND_USERS,
    DOMAIN,
    EVENT_MESSAGE_SENT,
    SEND_BURST,
    SEND_INTERVAL,
)

if TYPE_CHECKING:
    from . import MeshComConfigEntry

_LOGGER = logging.getLogger(__name__)

_LIMITER_KEY = f"{DOMAIN}_send_limiter"


class SendRateLimiter:
    """Token bucket shared by all nodes of this Home Assistant instance."""

    def __init__(self) -> None:
        self._tokens = float(SEND_BURST)
        self._updated = time.monotonic()

    def try_take(self) -> bool:
        """Take one token if available."""
        now = time.monotonic()
        refill = (now - self._updated) / SEND_INTERVAL.total_seconds()
        self._tokens = min(float(SEND_BURST), self._tokens + refill)
        self._updated = now
        if self._tokens < 1:
            return False
        self._tokens -= 1
        return True


def _limiter(hass: HomeAssistant) -> SendRateLimiter:
    limiter: SendRateLimiter = hass.data.setdefault(_LIMITER_KEY, SendRateLimiter())
    return limiter


async def async_check_send_permission(
    hass: HomeAssistant, entry_id: str, allowed_users: list[str], context: Context | None
) -> None:
    """Raise Unauthorized unless the caller may transmit."""
    user_id = context.user_id if context else None
    if user_id is None:
        return
    user = await hass.auth.async_get_user(user_id)
    if user is None:
        raise Unauthorized(context=context, config_entry_id=entry_id, permission="send")
    if user.is_admin or user_id in allowed_users:
        return
    raise Unauthorized(context=context, config_entry_id=entry_id, permission="send")


def allowed_users(options: dict[str, object]) -> list[str]:
    """User ids released for sending in the options."""
    users = options.get(CONF_SEND_USERS, [])
    return [user for user in users if isinstance(user, str)] if isinstance(users, list) else []


async def async_send_text(
    hass: HomeAssistant,
    entry: MeshComConfigEntry,
    destination: str,
    text: str,
    context: Context | None,
) -> None:
    """Check everything, then send the datagram to the entry's node."""
    runtime = entry.runtime_data
    node = runtime.node
    if not node.sending_enabled:
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="sending_disabled")
    await async_check_send_permission(
        hass, entry.entry_id, allowed_users(dict(entry.options)), context
    )
    try:
        data = build_text_message(destination, text)
    except InvalidOutgoingError as err:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="invalid_message",
            translation_placeholders={"reason": err.reason},
        ) from err
    if not _limiter(hass).try_take():
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="rate_limited",
            translation_placeholders={"seconds": str(int(SEND_INTERVAL.total_seconds()))},
        )
    try:
        runtime.send_datagram(data)
    except OSError as err:
        raise HomeAssistantError(translation_domain=DOMAIN, translation_key="send_failed") from err
    # Logged without the text: message content is not written to the log.
    _LOGGER.info("%s: message sent to %s", node.callsign, destination)
    hass.bus.async_fire(
        EVENT_MESSAGE_SENT,
        {
            "entry_id": entry.entry_id,
            "node": node.callsign,
            "destination": destination,
            "text": text,
        },
        context=context,
    )
