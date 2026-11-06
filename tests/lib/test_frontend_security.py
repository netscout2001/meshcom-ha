"""Static checks of the chat panel (security concept C-01).

Message text comes from the radio and is untrusted. The panel must only ever
set it as text: no HTML sinks, no code evaluation, no automatic links.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

PANEL = (
    Path(__file__).parents[2]
    / "custom_components"
    / "meshcom"
    / "frontend"
    / "meshcom-chat-panel.js"
)

FORBIDDEN = [
    r"\.innerHTML\b",
    r"\.outerHTML\b",
    r"insertAdjacentHTML",
    r"document\.write",
    r"\beval\s*\(",
    r"\bnew\s+Function\b",
    r"\bsetTimeout\s*\(\s*['\"`]",
    r"\bsetInterval\s*\(\s*['\"`]",
    r"createContextualFragment",
    r"DOMParser",
    r"\.srcdoc\b",
    r"\.href\s*=",
    r"setAttribute\s*\(\s*['\"](?:on|href|src)",
    r"\bunsafeHTML\b",
    r"\bimport\s*\(",
]


def _code() -> str:
    text = PANEL.read_text("utf-8")
    # The header comment names the forbidden functions on purpose.
    return re.sub(r"/\*.*?\*/", "", text, count=1, flags=re.S)


@pytest.mark.parametrize("pattern", FORBIDDEN)
def test_no_html_sinks(pattern: str) -> None:
    assert re.search(pattern, _code()) is None, pattern


def test_ascii_only() -> None:
    """Non-ASCII only as escapes; no hidden bidi or look-alike characters."""
    assert PANEL.read_bytes().isascii()


def test_text_is_set_as_text() -> None:
    """Message text and sender reach the DOM through textContent only."""
    code = _code()
    assert "textContent" in code
    assert 'dir = "auto"' in code
