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
from homeassistant.core import Context, EventOrigin, HomeAssistant, ServiceCall
from homeassistant.setup import async_setup_component
from homeassistant.util.yaml import load_yaml_dict
from pytest_homeassistant_custom_component.common import async_capture_events

from custom_components.meshcom.services import SEND_MESSAGE_SCHEMA

BLUEPRINT = (
    Path(__file__).parents[2] / "blueprints" / "automation" / "meshcom" / "notify_with_reply.yaml"
)
ENTRY = "entry-1"
PERSON = "person.operator"
#: Context of the operator's phone (set up in the fixture).
OPERATOR: dict[str, Context] = {}


def _press(hass: HomeAssistant, data: dict[str, Any], context: Context | None = None) -> None:
    """A button press in the Companion app (comes in from outside)."""
    hass.bus.async_fire(
        "mobile_app_notification_action",
        data,
        EventOrigin.remote,
        context=context or OPERATOR["context"],
    )


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
                    "reply_person": PERSON,
                    "groups": " 262, 20 ",
                    "reply_timeout": {"minutes": 5},
                },
            }
        },
    )
    user = await hass.auth.async_create_user("Operator")
    OPERATOR["context"] = Context(user_id=user.id)
    hass.states.async_set(PERSON, "home", {"user_id": user.id})
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
    assert note["title"] == "MeshCom \u00b7 DM"
    assert note["message"] == "QA1ABC-12: Hello"
    action = note["data"]["actions"][0]
    assert action["behavior"] == "textInput"
    assert note["data"]["tag"] == "meshcom-QA1ABC-12"

    _press(hass, {"action": action["action"], "reply_text": " Hi back "})
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
    assert note["title"] == "MeshCom \u00b7 262"
    action = note["data"]["actions"][0]["action"]

    # Another phone's button does not answer this notification.
    _press(hass, {"action": "SOMETHING_ELSE", "reply_text": "x"})
    # An empty answer sends nothing.
    _press(hass, {"action": action, "reply_text": "  "})
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
    _press(hass, {"action": action, "reply_text": "73"})
    await hass.async_block_till_done()
    assert sent[0].data["destination"] == "20"


async def test_radio_text_stays_text(hass: HomeAssistant, sent: list[ServiceCall]) -> None:
    """Text that looks like a number, a list or a template is passed on as text."""
    notified = async_capture_events(hass, "test_notify")
    texts = ["[1, 2]", "007", "{{ states('sun.sun') }}", "{'a': 1}", "True"]
    for index, text in enumerate(texts):
        hass.bus.async_fire("meshcom_message", _message(text=text, sender=f"QA{index}ABC-1"))
    await _until(notified, len(texts))
    assert [n.data["message"] for n in notified] == [
        f"QA{index}ABC-1: {text}" for index, text in enumerate(texts)
    ]


@pytest.mark.parametrize("reply", ["1e5", "True", "[1, 2]", "007", "{'a': 1}", "None"])
async def test_reply_stays_text(hass: HomeAssistant, sent: list[ServiceCall], reply: str) -> None:
    """A reply that looks like a number, a list or a boolean is sent verbatim (F-10)."""
    notified = async_capture_events(hass, "test_notify")
    hass.bus.async_fire(
        "meshcom_message", _message(destination="20", destination_kind="group", to_me=False)
    )
    await _until(notified, 1)
    action = notified[0].data["data"]["actions"][0]["action"]
    _press(hass, {"action": action, "reply_text": reply})
    await hass.async_block_till_done()
    assert len(sent) == 1
    assert sent[0].data["message"] == reply
    assert sent[0].data["destination"] == "20"


async def test_reply_only_by_chosen_person(hass: HomeAssistant, sent: list[ServiceCall]) -> None:
    """Another user's press (own Companion app, same action id) sends nothing."""
    notified = async_capture_events(hass, "test_notify")
    hass.bus.async_fire("meshcom_message", _message())
    await _until(notified, 1)
    action = notified[0].data["data"]["actions"][0]["action"]
    assert action.startswith("MESHCOM_REPLY_")
    other = await hass.auth.async_create_user("Other")
    _press(hass, {"action": action, "reply_text": "hijack"}, Context(user_id=other.id))
    _press(hass, {"action": action, "reply_text": "no user"}, Context())
    for _ in range(20):
        await asyncio.sleep(0)
    assert sent == []
    # The run still waits for the operator.
    _press(hass, {"action": action, "reply_text": "73"})
    await hass.async_block_till_done()
    assert [call.data["message"] for call in sent] == ["73"]


async def test_message_event_from_outside_ignored(
    hass: HomeAssistant, sent: list[ServiceCall]
) -> None:
    """A message event fired from outside (webhook) does not notify."""
    notified = async_capture_events(hass, "test_notify")
    hass.bus.async_fire("meshcom_message", _message(), EventOrigin.remote)
    for _ in range(20):
        await asyncio.sleep(0)
    assert notified == []


async def test_person_without_user_cannot_reply(
    hass: HomeAssistant, sent: list[ServiceCall]
) -> None:
    """Without a user the notification comes, but no reply is waited for."""
    hass.states.async_set(PERSON, "home", {})
    notified = async_capture_events(hass, "test_notify")
    hass.bus.async_fire("meshcom_message", _message())
    await hass.async_block_till_done()
    assert len(notified) == 1
    action = notified[0].data["data"]["actions"][0]["action"]
    _press(hass, {"action": action, "reply_text": "73"}, Context())
    await hass.async_block_till_done()
    assert sent == []
