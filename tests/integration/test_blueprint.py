"""The notify-with-reply blueprint, run end to end in Home Assistant.

The phone notification (a mobile_app device action) is replaced by an event,
and ``meshcom.send_message`` by a recording service, so the blueprint's own
logic is tested: which messages notify, what the notification carries, and
where the reply goes.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from homeassistant.components.automation.config import AUTOMATION_BLUEPRINT_SCHEMA
from homeassistant.components.blueprint import models
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.setup import async_setup_component
from homeassistant.util.yaml import load_yaml_dict
from pytest_homeassistant_custom_component.common import async_capture_events

from custom_components.meshcom.services import SEND_MESSAGE_SCHEMA

BLUEPRINT = (
    Path(__file__).parents[2] / "blueprints" / "automation" / "meshcom" / "notify_with_reply.yaml"
)
ENTRY = "entry-1"


async def _until(events: list[Any], count: int) -> None:
    """Let the automation run until it waits for the reply.

    ``async_block_till_done`` would wait for the reply itself.
    """
    for _ in range(100):
        if len(events) >= count:
            return
        await asyncio.sleep(0)
    raise AssertionError(f"expected {count} notifications, got {len(events)}")


def _message(**extra: Any) -> dict[str, Any]:
    data = {
        "entry_id": ENTRY,
        "node": "QX1YZ-12",
        "sender": "QA1ABC-12",
        "path": [],
        "destination": "QX1YZ-12",
        "destination_kind": "direct",
        "text": "Hello",
        "is_own": False,
        "to_me": True,
        "via_server": False,
    }
    data.update(extra)
    return data


@pytest.fixture
async def sent(hass: HomeAssistant) -> list[ServiceCall]:
    """Set up the blueprint; return the recorded send_message calls."""
    blueprint = models.Blueprint(
        load_yaml_dict(str(BLUEPRINT)),
        expected_domain="automation",
        schema=AUTOMATION_BLUEPRINT_SCHEMA,
    )
    inputs = models.BlueprintInputs(
        blueprint,
        {
            "use_blueprint": {
                "path": "meshcom/notify_with_reply.yaml",
                "input": {
                    "node": ENTRY,
                    "notify_device": "phone-device",
                    "groups": " 262, 20 ",
                    "reply_timeout": {"minutes": 5},
                },
            }
        },
    )
    config = inputs.async_substitute()
    config.pop("use_blueprint", None)
    # The phone: a device action in the blueprint, an event here.
    notify = config["actions"][1]
    assert notify["domain"] == "mobile_app"
    assert notify["device_id"] == "phone-device"
    config["actions"][1] = {
        "event": "test_notify",
        "event_data": {k: notify[k] for k in ("title", "message", "data")},
    }
    config["id"] = "meshcom_notify"
    calls: list[ServiceCall] = []

    async def _record(call: ServiceCall) -> None:
        calls.append(call)

    # Same schema as the real action: it turns "20" (a number after
    # Home Assistant's template typing) back into the string "20".
    hass.services.async_register("meshcom", "send_message", _record, schema=SEND_MESSAGE_SCHEMA)
    assert await async_setup_component(hass, "automation", {"automation": [config]})
    await hass.async_block_till_done()
    return calls


async def test_direct_message_reply(hass: HomeAssistant, sent: list[ServiceCall]) -> None:
    """A direct message notifies; the reply goes back to the sender."""
    notified = async_capture_events(hass, "test_notify")
    hass.bus.async_fire("meshcom_message", _message())
    await _until(notified, 1)
    assert len(notified) == 1
    note = notified[0].data
    assert note["title"] == "MeshCom: QA1ABC-12"
    assert note["message"] == "Hello"
    action = note["data"]["actions"][0]
    assert action["behavior"] == "textInput"
    assert note["data"]["tag"] == "meshcom-QA1ABC-12"

    hass.bus.async_fire(
        "mobile_app_notification_action", {"action": action["action"], "reply_text": " Hi back "}
    )
    await hass.async_block_till_done()
    assert len(sent) == 1
    assert sent[0].data == {
        "config_entry_id": ENTRY,
        "destination": "QA1ABC-12",
        "message": "Hi back",
    }


async def test_group_reply_and_filters(hass: HomeAssistant, sent: list[ServiceCall]) -> None:
    """Only chosen groups notify; the reply goes into the group."""
    notified = async_capture_events(hass, "test_notify")
    group = {"destination": "262", "destination_kind": "group", "to_me": False}
    hass.bus.async_fire("meshcom_message", _message(**group))
    for skipped in (
        _message(destination="9", destination_kind="group", to_me=False),  # other group
        _message(destination="*", destination_kind="broadcast", to_me=False),  # off
        _message(is_own=True),  # own message
        _message(entry_id="other-node"),  # other node
        _message(destination="QB2DEF-1", to_me=False),  # DM between others
    ):
        hass.bus.async_fire("meshcom_message", skipped)
    await _until(notified, 1)
    for _ in range(20):
        await asyncio.sleep(0)
    assert len(notified) == 1
    note = notified[0].data
    assert note["title"] == "MeshCom: QA1ABC-12 → 262"
    action = note["data"]["actions"][0]["action"]

    # Another phone's button does not answer this notification.
    hass.bus.async_fire(
        "mobile_app_notification_action", {"action": "SOMETHING_ELSE", "reply_text": "x"}
    )
    # An empty answer sends nothing.
    hass.bus.async_fire("mobile_app_notification_action", {"action": action, "reply_text": "  "})
    await hass.async_block_till_done()
    assert sent == []


async def test_group_reply_sent(hass: HomeAssistant, sent: list[ServiceCall]) -> None:
    """The answer to a group message goes to that group."""
    notified = async_capture_events(hass, "test_notify")
    hass.bus.async_fire(
        "meshcom_message", _message(destination="20", destination_kind="group", to_me=False)
    )
    await _until(notified, 1)
    action = notified[0].data["data"]["actions"][0]["action"]
    hass.bus.async_fire("mobile_app_notification_action", {"action": action, "reply_text": "73"})
    await hass.async_block_till_done()
    assert sent[0].data["destination"] == "20"
