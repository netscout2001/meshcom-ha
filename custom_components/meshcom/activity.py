"""Messages per hour of one node for the last 48 hours (panel diagram).

Kept apart from the chat history: that one holds 500 messages, which a busy
node fills in a few hours. Here only counters per hour are stored.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any, Final

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

ACTIVITY_STORE_VERSION: Final = 1
ACTIVITY_SAVE_DELAY: Final = 120
#: Hours shown in the panel.
ACTIVITY_HOURS: Final = 48
#: What is counted per hour.
KINDS: Final = ("received_direct", "received_group", "received_all", "sent")
_MAX_COUNT: Final = 100_000


def _hour(when: datetime) -> datetime:
    return dt_util.as_utc(when).replace(minute=0, second=0, microsecond=0)


class ActivityLog:
    """Hourly message counters, stored so a restart keeps the diagram."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        #: Hour (UTC, full hour) -> counter per kind.
        self.buckets: dict[datetime, dict[str, int]] = {}
        self._store: Store[dict[str, Any]] = Store(
            hass, ACTIVITY_STORE_VERSION, f"{DOMAIN}.activity.{entry_id}"
        )

    async def async_load(self) -> None:
        """Read the stored counters; anything odd is skipped."""
        try:
            data = await self._store.async_load()
        except (ValueError, OSError):  # pragma: no cover - broken file, start empty
            _LOGGER.warning("Stored message activity is unreadable and is ignored")
            return
        raw = data.get("hours") if isinstance(data, Mapping) else None
        if not isinstance(raw, Mapping):
            return
        oldest = _hour(dt_util.utcnow()) - timedelta(hours=ACTIVITY_HOURS)
        for key, counts in list(raw.items())[: ACTIVITY_HOURS * 2]:
            hour = dt_util.parse_datetime(key) if isinstance(key, str) else None
            if hour is None or hour.tzinfo is None or not isinstance(counts, Mapping):
                continue
            hour = _hour(hour)
            if hour <= oldest:
                continue
            self.buckets[hour] = {
                kind: value
                for kind in KINDS
                if isinstance(value := counts.get(kind), int)
                and not isinstance(value, bool)
                and 0 <= value <= _MAX_COUNT
            }

    def _data(self) -> dict[str, Any]:
        return {"hours": {hour.isoformat(): dict(counts) for hour, counts in self.buckets.items()}}

    async def async_save_now(self) -> None:
        """Write pending counters right away (unload)."""
        await self._store.async_save(self._data())

    async def async_remove(self) -> None:
        """Delete the stored counters (entry removed)."""
        await self._store.async_remove()

    def add(self, kind: str, when: datetime) -> None:
        """Count one message of ``kind`` in the hour of ``when``."""
        hour = _hour(when)
        counts = self.buckets.setdefault(hour, {})
        counts[kind] = min(_MAX_COUNT, counts.get(kind, 0) + 1)
        oldest = hour - timedelta(hours=ACTIVITY_HOURS)
        for old in [old for old in self.buckets if old <= oldest]:
            del self.buckets[old]
        self._store.async_delay_save(self._data, ACTIVITY_SAVE_DELAY)

    def series(self, now: datetime) -> dict[str, Any]:
        """The last 48 hours, oldest first, with zeros for quiet hours."""
        last = _hour(now)
        hours = [last - timedelta(hours=offset) for offset in range(ACTIVITY_HOURS - 1, -1, -1)]
        return {
            "hours": [hour.isoformat() for hour in hours],
            **{kind: [self.buckets.get(hour, {}).get(kind, 0) for hour in hours] for kind in KINDS},
        }
