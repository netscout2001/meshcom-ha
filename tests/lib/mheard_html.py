"""The node's MHeard page, rendered like sub_page_mheard() in web_functions.cpp (4.40a).

Callsigns and positions are invented (Q prefixes are not issued; positions
in a neutral demo area).
"""

from __future__ import annotations

from dataclasses import dataclass

LEGEND = (
    '<p style="font-size:var(--fs-s);color:#555;max-width:900px;">'
    "Stations I heard directly in the last 3 h, newest first. ...</p>"
)


@dataclass
class Card:
    """One station as the firmware has it (NbrMhView)."""

    call: str
    age_min: int = 0
    plt: str = "@"
    hw: str = "TBEAM_AXP2101"
    fw: str = "v4.40a"
    rssi: int | None = -110
    snr: int | None = -8
    dist: float | None = 6.6
    lat: float | None = 50.123
    lon: float | None = 8.456
    alt: int | None = 491
    hm_snr: int | None = -11
    role: str = "R"
    ex: int = 0
    nb: int = 7
    ncnt: int = 6
    gw: bool = False


def _field(name: str, value: str, title: str = "") -> str:
    attr = f' title="{title}"' if title else ""
    return f'<div><span class="font-bold">{name}:</span><br><span{attr}>{value}</span></div>'


def _plural(n: int) -> str:
    return "" if n == 1 else "s"


def card(c: Card, stamp: str = "2026.11.09 22:04:23") -> str:
    """One card, field for field like the firmware's printf calls."""
    out = '<div class="cardlayout" style="max-width:900px;">\n'
    out += (
        f'<label class="cardlabel"><a href="https://aprs.fi/?call={c.call}" target="_blank">'
        f'{c.call}</a> <span class="font-small">({stamp})</span></label>'
    )
    out += '<div class="flex-auto-wrap">'
    frame = {":": "Text message", "!": "Position", "@": "Heartbeat (HEY)"}.get(c.plt, "???")
    out += _field("Last frame", frame)
    out += _field("Hardware", c.hw)
    out += _field("Firmware", c.fw)
    out += _field(
        "Country / mode", "8 / 8", "high nibble: country index, low nibble: LoRa modulation"
    )
    out += _field("RSSI", "" if c.rssi is None else f"{c.rssi} dBm")
    out += _field("SNR (avg)", "-" if c.snr is None else f"{c.snr} dB")
    out += _field("Distance", "-" if c.dist is None else f"{c.dist:.1f} km")
    if c.lat is not None and c.lon is not None:
        out += _field("Lat", f"{'N' if c.lat >= 0 else 'S'}{abs(c.lat):06.3f}")
        out += _field("Lon", f"{'E' if c.lon >= 0 else 'W'}{abs(c.lon):07.3f}")
    else:
        out += _field("Lat", "") + _field("Lon", "")
    out += _field("Altitude", "-" if c.alt is None else f"{c.alt} m")
    out += '</div><div class="flex-auto-wrap" style="margin-top:8px;">'
    out += _field("Last heard", f"{c.age_min} min ago")
    out += _field("Hears me", "not reported" if c.hm_snr is None else f"yes, {c.hm_snr} dB")
    out += _field(
        "Relay role", {"S": "Super node", "N": "Needed", "R": "Redundant"}.get(c.role, "-")
    )
    out += _field("Only it hears", f"{c.ex} station{_plural(c.ex)}")
    out += _field("It hears", f"{c.nb} station{_plural(c.nb)}")
    out += _field("It reports", f"{c.ncnt} neighbour{_plural(c.ncnt)}")
    out += _field("Gateway", "yes" if c.gw else "no")
    out += "</div></div>"
    return out


def page(cards: list[Card]) -> str:
    """The whole page as the node sends it for ``/?page=mheard``."""
    body = '<div id="content_title"><h1 class="font-bold">MHeard Information</h1></div>\n'
    body += '<div id="content_inner">\n' + LEGEND
    body += "".join(card(c) for c in cards)
    if not cards:
        body += "<p>No Nodes heard so far.</p>\n"
    return body + "</div>\n\n"
