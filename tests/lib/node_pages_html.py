"""Info, position and RX log pages, rendered like web_functions.cpp (firmware 4.40a).

All values are invented; no real network names, addresses or positions.
"""

from __future__ import annotations


def subheader(title: str, now: str = "2026-11-10&nbsp;16:41:39") -> str:
    """_create_meshcom_subheader(): node time, zone, time source, title."""
    return (
        f'<div id="content_title"><p class="font-small">{now}&nbsp;CET&nbsp;[GPS]</p>'
        f'<h1 class="font-bold">{title}</h1></div>'
    )


def info_page(
    *,
    now: str = "2026-11-10&nbsp;16:41:39",
    start: str = "2026-11-08 13:13:35",
    server: str = "Internet meshcom.example, connected (last rx 10 s)",
    hardware: str = "TBEAM_AXP2101",
    wifi: bool = True,
    blocked: str = "none (dropped 0)",
) -> str:
    """sub_page_info(), the rows the integration reads plus their neighbours."""
    rows = [
        "<tr><td>Firmware</td><td>Meshcom 4.40a<br>(build: Nov  8 2026 / 01:51:18)"
        "<br>(flash-version 20260724)</td></tr>",
        f"<tr><td>Start Date</td><td>{start}</td></tr>",
        "<tr><td>Call</td><td>QX1YZ-12</td></tr>",
        f"<tr><td>Hardware</td><td>{hardware}</td></tr>",
        "<tr><td>UTC offset</td><td>1.0 [GPS]</td></tr>",
        "<tr><td>Battery</td><td>4.157V (96%) max 4.200V, full</td></tr>",
        "<tr><td>Settings</td><td>Gateway: on<br>Mesh: on<br></td></tr>",
        "<tr><td>Network</td><td>"
        f"Server: {server}<br>ext UDP: on<br>net console: off<br>KISS/TCP: off<br>"
        "KISS TX: off<br>KISS RxMeta: off<br>KISS Auth: off<br></td></tr>",
        "<tr><td>Mesh settings</td><td>max_hop_text: 4<br>max_hop_pos: 2<br></td></tr>",
        "<tr><td>Country</td><td>EU8</td></tr>",
        "<tr><td>Frequency</td><td>433.1750 MHz</td></tr>",
        "<tr><td>Bandwidth</td><td>250 kHz</td></tr>",
        "<tr><td>Spreading Factor (SF)</td><td>11</td></tr>",
        "<tr><td>Coding Rate (CR)</td><td>6</td></tr>",
        "<tr><td>TX Power</td><td>20 dBm (100.00 mW)</td></tr>",
    ]
    if wifi:
        rows += [
            "<tr><td>WiFi SSID</td><td>ExampleNet</td></tr>",
            "<tr><td>WiFi BSSID</td><td>02:00:00:00:00:01</td></tr>",
            "<tr><td>WiFi RSSI</td><td>-56</td></tr>",
            "<tr><td>IP address</td><td>192.0.2.15</td></tr>",
        ]
    rows.append(f"<tr><td>Blocked calls</td><td>{blocked}</td></tr>")
    return (
        subheader("Node Information", now)
        + '<div id="content_inner">\n<table class="table mw-600">\n'
        + '<thead><tr class="font-bold"><td>Item</td><td>Value</td></tr></thead>\n'
        + "\n".join(rows)
        + "\n</table></div>\n"
    )


def position_page(
    *, satellites: str = "10 - fix - HDOP 0", rate: int = 1800, next_s: int = 1275, gps: str = "on"
) -> str:
    """sub_page_position(): the coordinates are invented."""
    rows = [
        "<tr><td>Latitude</td><td>50.1234 N</td></tr>",
        "<tr><td>Longitude</td><td>8.4567 E</td></tr>",
        "<tr><td>Altitude</td><td>500</td></tr>",
        f"<tr><td>Satellites</td><td>{satellites}</td></tr>",
        f"<tr><td>Rate</td><td>{rate}</td></tr>",
        f"<tr><td>Next</td><td>{next_s} sec</td></tr>",
        "<tr><td>Distance</td><td>0 m</td></tr>",
        f"<tr><td>GPS</td><td>{gps}</td></tr>",
        "<tr><td>Track</td><td>off</td></tr>",
    ]
    return (
        subheader("Position Information")
        + '<div id="content_inner">\n<table class="table mw-600">\n'
        + "\n".join(rows)
        + "\n</table></div>\n"
    )


def rxlog_page(**values: int | str) -> str:
    """sub_page_rxlog(): the #mcq div with its data attributes, then log lines."""
    data: dict[str, int | str] = {
        "ring": 20, "p0": 1, "p1": 0, "p2": 0, "p3": 0, "p4": 0, "p5": 1,
        "bp": 0, "bpname": "ok", "qrs": 5, "qrsf": 7, "qrt": 16,
        "win": 1, "rx": 34200, "tx": 13200, "int": 300, "newid": 13,
        "dup": 8, "dedup": 64, "dwin": 27, "age": 186, "drop": 0,
        "w0": 0, "w1": 0, "w2": 0, "w3": 0, "w4": 0, "w5": 0,
    }  # fmt: skip
    data.update(values)

    def attrs(*names: str) -> str:
        return " ".join(f'data-{name}="{data[name]}"' for name in names)

    div = (
        f'<div id="mcq" {attrs("ring", "p0", "p1", "p2", "p3")}\n'
        f" {attrs('p4', 'p5', 'bp', 'bpname', 'qrs', 'qrsf', 'qrt')}\n"
        f" {attrs('win', 'rx', 'tx', 'int', 'newid')}\n"
        f" {attrs('dup', 'dedup', 'dwin', 'age', 'drop')}\n"
        f" {attrs('w0', 'w1', 'w2', 'w3', 'w4', 'w5')}></div>\n"
    )
    return (
        subheader("RX Log")
        + '<div id="content_inner" class="logoutput">\n'
        + '<div class="cardlayout" style="width:600px;max-width:100%;box-sizing:border-box;">\n'
        + '<label class="cardlabel">LoRa Queue</label>\n'
        + '<button id="mcqtogglebtn" class="mcq-toggle" onclick="mcQueueToggle(this)">'
        + "hide</button>\n"
        + div
        + "</div>\n"
        + '<div style="overflow:scroll;">\n'
        + "<p>&lt;14&gt;16:41:26 :A5351139 2 001 8/8 LH:8C QR1ABC-12&gt;* !5007.40N/00827.40E</p>\n"
    )
