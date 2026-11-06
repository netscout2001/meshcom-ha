"""Sidebar panel "MeshCom" (chat).

The panel is a plain web component shipped with the integration. It is
registered while at least one node is loaded.
"""

from __future__ import annotations

import json
from pathlib import Path

from homeassistant.components import frontend, panel_custom
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant

from .const import DOMAIN

PANEL_URL_PATH = "meshcom-chat"
PANEL_ELEMENT = "meshcom-chat-panel"
STATIC_URL = f"/{DOMAIN}_static"
_FRONTEND_DIR = Path(__file__).parent / "frontend"
_DATA_STATIC = f"{DOMAIN}_static_registered"
_DATA_PANEL = f"{DOMAIN}_panel_registered"


def _version() -> str:
    manifest = json.loads((Path(__file__).parent / "manifest.json").read_text("utf-8"))
    return str(manifest["version"])


async def async_register_panel(hass: HomeAssistant) -> None:
    """Serve the panel's file and add the sidebar entry."""
    if not hass.data.get(_DATA_STATIC):
        await hass.http.async_register_static_paths(
            [StaticPathConfig(STATIC_URL, str(_FRONTEND_DIR), cache_headers=False)]
        )
        hass.data[_DATA_STATIC] = True
    if hass.data.get(_DATA_PANEL):
        return
    version = await hass.async_add_executor_job(_version)
    await panel_custom.async_register_panel(
        hass,
        frontend_url_path=PANEL_URL_PATH,
        webcomponent_name=PANEL_ELEMENT,
        sidebar_title="MeshCom",
        sidebar_icon="mdi:message-text-outline",
        module_url=f"{STATIC_URL}/{PANEL_ELEMENT}.js?v={version}",
        require_admin=False,
    )
    hass.data[_DATA_PANEL] = True


def async_unregister_panel(hass: HomeAssistant) -> None:
    """Remove the sidebar entry (last node unloaded)."""
    if hass.data.pop(_DATA_PANEL, False):
        frontend.async_remove_panel(hass, PANEL_URL_PATH, warn_if_unknown=False)
