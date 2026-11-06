"""Cleaning of free text received from the mesh.

Message text is untrusted. Control characters would allow log injection
(a newline that forges a log line), and bidirectional or zero-width format
characters can make a text look different from what it is ("Trojan Source").
Both are removed for display; the caller learns that something was removed
(security concept C-08).

This module does not escape HTML. Escaping belongs to the render layer; the
frontend must only ever insert text as text (security concept C-01).
"""

from __future__ import annotations

import unicodedata
from typing import Final

# Bidirectional controls and invisible format characters.
_FORMAT_CHARS: Final = frozenset(
    [
        "\u061c",  # ARABIC LETTER MARK
        "\u200b",  # ZERO WIDTH SPACE
        "\u200c",  # ZERO WIDTH NON-JOINER
        "\u200d",  # ZERO WIDTH JOINER
        "\u200e",  # LEFT-TO-RIGHT MARK
        "\u200f",  # RIGHT-TO-LEFT MARK
        "\u202a",  # LEFT-TO-RIGHT EMBEDDING
        "\u202b",  # RIGHT-TO-LEFT EMBEDDING
        "\u202c",  # POP DIRECTIONAL FORMATTING
        "\u202d",  # LEFT-TO-RIGHT OVERRIDE
        "\u202e",  # RIGHT-TO-LEFT OVERRIDE
        "\u2060",  # WORD JOINER
        "\u2066",  # LEFT-TO-RIGHT ISOLATE
        "\u2067",  # RIGHT-TO-LEFT ISOLATE
        "\u2068",  # FIRST STRONG ISOLATE
        "\u2069",  # POP DIRECTIONAL ISOLATE
        "\ufeff",  # ZERO WIDTH NO-BREAK SPACE
    ]
)


def _is_unwanted(char: str) -> bool:
    return char in _FORMAT_CHARS or unicodedata.category(char) == "Cc"


def clean_text(value: str) -> tuple[str, bool]:
    """Remove control and invisible format characters.

    Returns the cleaned text and whether anything was removed.
    """
    cleaned = "".join(char for char in value if not _is_unwanted(char))
    return cleaned, cleaned != value


def contains_unwanted(value: str) -> bool:
    """Return True if ``value`` contains control or invisible format characters."""
    return any(_is_unwanted(char) for char in value)
