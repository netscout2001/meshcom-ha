"""Values from the node's info, position and RX log pages."""

from __future__ import annotations

import pytest

from aiomeshcom.webpages import (
    GpsInfo,
    NodeInfo,
    RadioStats,
    UpdateStatus,
    parse_node_info,
    parse_position_page,
    parse_rxlog_page,
    parse_update_status,
)
from tests.lib.node_pages_html import info_page, position_page, rxlog_page


def test_node_info() -> None:
    """All values of the info page, as the firmware prints them."""
    assert parse_node_info(info_page()) == NodeInfo(
        uptime_seconds=2 * 86400 + 3 * 3600 + 28 * 60 + 4,
        hardware="TBEAM_AXP2101",
        frequency_mhz=433.175,
        bandwidth_khz=250,
        spreading_factor=11,
        coding_rate=6,
        tx_power_dbm=20,
        wifi_rssi=-56,
        server="connected",
        server_age_seconds=10,
        max_hop_text=4,
        max_hop_pos=2,
        blocked_dropped=0,
    )


@pytest.mark.parametrize(
    ("server", "state", "age"),
    [
        ("Internet meshcom.example, connected (last rx 10 s)", "connected", 10),
        ("Hamnet 44.0.0.1, no response for 913 s", "lost", 913),
        ("Internet meshcom.example, no response yet", "waiting", None),
        ("Internet, no IP address", "no_ip", None),
        ("no IP address", "no_ip", None),
        ("not selected", "not_selected", None),
        ("off", "off", None),
        ("something new", None, None),
    ],
)
def test_node_info_server(server: str, state: str | None, age: int | None) -> None:
    """Every form of the server line (gw_link_status.cpp); unknown ones give None."""
    info = parse_node_info(info_page(server=server))
    assert (info.server, info.server_age_seconds) == (state, age)


def test_node_info_never_reads_network_details() -> None:
    """WLAN name, BSSID and IP address are not part of the result."""
    text = repr(parse_node_info(info_page()))
    assert "ExampleNet" not in text
    assert "02:00:00" not in text
    assert "192.0.2" not in text


def test_node_info_odd_values() -> None:
    """Missing or implausible values are None, the rest stays."""
    info = parse_node_info(
        info_page(
            start="2026-11-11 13:13:35",  # after "now": clock jump
            hardware="<b>x</b>",
            wifi=False,
            blocked="QA1ABC-1 (dropped -3)",
        )
    )
    assert info.uptime_seconds is None
    assert info.hardware is None
    assert info.wifi_rssi is None
    assert info.blocked_dropped is None
    assert info.spreading_factor == 11
    assert parse_node_info(info_page(start="2026-13-45 99:99:99")).uptime_seconds is None
    assert parse_node_info("") == NodeInfo()


def test_position_page() -> None:
    """GPS state, not the position itself."""
    assert parse_position_page(position_page()) == GpsInfo(
        enabled=True, satellites=10, fix=True, hdop=0, beacon_interval=1800, next_beacon=1275
    )
    gps = parse_position_page(position_page(satellites="0 - nofix - HDOP 99", gps="off"))
    assert gps is not None
    assert (gps.enabled, gps.satellites, gps.fix) == (False, 0, False)
    assert parse_position_page("<h1>Login</h1>") is None
    # A node that just sent its beacon may show a negative countdown.
    late = parse_position_page(position_page(next_s=-3))
    assert late is not None
    assert late.next_beacon is None


def test_rxlog_page() -> None:
    """The LoRa queue panel; percentages computed like the firmware does."""
    assert parse_rxlog_page(rxlog_page()) == RadioStats(
        queue_used=1,
        queue_size=20,
        queue_by_priority={"crit": 0, "high": 0, "normal": 0, "low": 0, "bg": 1},
        waiting_ack=0,
        slow_down_at=5,
        refuse_at=16,
        state="accepted",
        rx_percent=11.4,
        tx_percent=4.4,
        dropped=0,
        new_ids=13,
        duplicates=8,
        dedup_window_minutes=27,
        window_age_seconds=186,
    )


def test_rxlog_page_before_first_window() -> None:
    """Before the first 5-minute window only the queue is known."""
    stats = parse_rxlog_page(rxlog_page(win=0, bp=1))
    assert stats is not None
    assert (stats.rx_percent, stats.tx_percent, stats.duplicates) == (None, None, None)
    assert stats.state == "slow_down"
    assert stats.queue_used == 1


@pytest.mark.parametrize(
    "values",
    [
        {"ring": 0},  # no queue size
        {"p0": 25},  # more used than slots
        {"p0": "x"},
        {"ring": "<script>"},
    ],
)
def test_rxlog_page_rejected(values: dict[str, int | str]) -> None:
    """A queue panel that does not add up gives None."""
    assert parse_rxlog_page(rxlog_page(**values)) is None


def test_rxlog_page_clamps_and_checks() -> None:
    """Busy time above the window counts as 100 %, odd single values as None."""
    stats = parse_rxlog_page(rxlog_page(rx=999999, bp=7, drop=-1, p3="many"))
    assert stats is not None
    assert stats.rx_percent == 100.0
    assert stats.state is None
    assert stats.dropped is None
    assert stats.queue_by_priority["normal"] == 0
    assert parse_rxlog_page("") is None
    assert parse_rxlog_page(info_page()) is None


# --- firmware update state (/austatus) ----------------------------------------

_UPDATE: dict[str, object] = {
    "st": "busy",
    "job": "download",
    "run": "v4.40a.11.07",
    "avail": "v4.40a.11.20",
    "newer": 1,
    "inst": 1,
    "staged": "",
    "err": "",
    "pct": 42,
    "phone": 0,
    "sbok": 1,
}


def test_parse_update_status() -> None:
    """The known shape gives all values."""
    status = parse_update_status(_UPDATE)
    assert status == UpdateStatus(
        running="v4.40a.11.07",
        available="v4.40a.11.20",
        newer=True,
        installable=True,
        staged=None,
        state="busy",
        job="download",
        percent=42,
        error=None,
        safeboot_ok=True,
        phone=False,
    )


def test_parse_update_status_error_code() -> None:
    """Only the code of an error is kept; odd codes are dropped."""
    status = parse_update_status({**_UPDATE, "st": "fail", "err": "lowheap_phone 41234"})
    assert status is not None
    assert status.error == "lowheap_phone"
    status = parse_update_status({**_UPDATE, "err": "<b>x</b>"})
    assert status is not None
    assert status.error is None


@pytest.mark.parametrize(
    "change",
    [
        {"run": ""},
        {"run": "v4<script>"},
        {"st": "weird"},
        {"st": []},
        {"job": {"a": 1}},
        {"job": "flash"},
        {"newer": True},
        {"inst": 2},
        {"sbok": "1"},
        {"phone": None},
        {"pct": 101},
        {"pct": -1},
        {"pct": True},
        {"pct": "5"},
    ],
)
def test_parse_update_status_rejects(change: dict[str, object]) -> None:
    """Anything outside the known shape gives None."""
    assert parse_update_status({**_UPDATE, **change}) is None


def test_parse_update_status_not_an_object() -> None:
    """A list or a string is no update state."""
    assert parse_update_status([1, 2]) is None
    assert parse_update_status("ok") is None


def test_parse_update_status_bad_tags() -> None:
    """An invalid available or staged tag is unknown, not an error."""
    status = parse_update_status({**_UPDATE, "avail": "x" * 40, "staged": "v4.40a.11.20"})
    assert status is not None
    assert status.available is None
    assert status.staged == "v4.40a.11.20"
