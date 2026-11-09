# MeshCom for Home Assistant

> **Status: beta.** Feedback and bug reports are welcome in the
> [issue tracker](https://github.com/netscout2001/meshcom-ha/issues).

A Home Assistant integration for the [MeshCom](https://icssw.org/en/meshcom/)
LoRa mesh network (433 MHz amateur radio). It shows your own MeshCom nodes and
the stations they hear, lets you read and send messages (broadcast, groups,
direct messages with delivery status) from the MeshCom panel (chat, nodes,
stations), dashboards and automations, and switches node settings such as
**No MSG All**.

Everything sent goes out on amateur radio under your node's callsign. Use it
only with a valid licence and the node's callsign.

![MeshCom panel: chat with groups, direct messages and unread counters](docs/images/panel-chat.png)

## Contents

- [Screenshots](#screenshots)
- [Supported devices](#supported-devices)
- [Installation](#installation)
- [Configuration](#configuration)
- [What you get](#what-you-get)
- [Actions and events](#actions-and-events)
- [Data updates](#data-updates)
- [Examples](#examples)
- [Known limitations](#known-limitations)
- [Troubleshooting](#troubleshooting)
- [Removal](#removal)
- [Security](#security)
- [Development](#development)

## Screenshots

All screenshots use invented data: the callsigns start with `Q`, a prefix
that is not assigned to any country, so none of them belongs to a real
station.

| | |
| --- | --- |
| ![Chat](docs/images/panel-chat.png) | ![Nodes](docs/images/panel-nodes.png) |
| **Chat**: conversations for all, groups and direct messages; path and signal of every message, unread counters, "New messages" line | **Nodes**: one card per own node with its sensors and switches |
| ![Stations](docs/images/panel-stations.png) | ![Station on the map](docs/images/panel-stations-popup.png) |
| **Stations**: map of the own node and the heard stations (colour by last heard), sortable table below | **Map**: a click on a station shows its values, with buttons for a direct message and OpenStreetMap |
| ![Add a node](docs/images/ha-add-node.png) | ![Integration page](docs/images/ha-integration.png) |
| **Setup**: choose external UDP or KISS over TCP | **Integration page**: one entry per node |
| ![UDP setup](docs/images/ha-add-udp.png) | ![KISS setup](docs/images/ha-add-kiss.png) |
| **External UDP** setup | **KISS over TCP** setup |
| ![Options](docs/images/ha-options.png) | ![Station options](docs/images/ha-options-stations.png) |
| **Options**: groups, users who may send, own groups only | **Options**: how heard stations appear |

## Supported devices

- MeshCom nodes with firmware **4.40a** (tested). Firmware 4.34z to 4.40a
  have the same web API; older firmware has no web API (UDP still works).
- **External UDP** works on every node with the "ext UDP" function.
- **KISS over TCP** needs an ESP32-based node with firmware 4.40a.
- Several nodes at once, each as its own entry; UDP nodes share one port.

## Installation

### HACS (recommended)

1. In HACS search for **MeshCom**, install it and restart Home Assistant.
2. If HACS does not find it (the listing in the HACS default repositories is
   still under review), add it as a custom repository first: HACS menu
   (three dots) → **Custom repositories**, add
   `https://github.com/netscout2001/meshcom-ha` with type **Integration**,
   then search again.

HACS installs the latest release and reports new ones as updates.

### Manual

Copy `custom_components/meshcom` from the latest release into the
`custom_components` folder of your configuration and restart Home Assistant.

The integration icon needs Home Assistant 2026.3 or newer; the integration
itself runs on 2025.6 or newer.

## Configuration

**Settings → Devices & services → Add integration → MeshCom.** First choose
how Home Assistant reaches the node.

### External UDP (node in the home network)

On the node set **ext. UDP IP** to the address of Home Assistant and enable
**ext UDP** (`--extudpip <ip>`, `--extudp on`).

| Field | Meaning |
| --- | --- |
| Node IP address | Private IPv4 address of the node |
| UDP port in Home Assistant | 1799; the node always sends to this port |

While Home Assistant waits, click **Send Position** on the node's web page.
The node is identified by the callsign in its own beacon.

A node is identified by its callsign for both access paths. If you move a
node from KISS to UDP or back (delete the entry and add it again with the
other access path), its device and entities come back with the same entity
ids and history.

### KISS over TCP (e.g. a mobile node)

On the node: `--kiss on`, for sending from Home Assistant `--kiss tx on`, for
RSSI/SNR `--kiss meta on`, and protect it with `--kiss auth on` and the node
password `--passwd`.

| Field | Meaning |
| --- | --- |
| Node IP address | Private IPv4 address of the node |
| KISS port | 8001 |
| Callsign of the node | The node's own callsign with SSID, e.g. `QX1YZ-9` |
| Node password | `--passwd` (1 to 14 characters); empty only if KISS authentication is off |

### Web password (both access paths)

Next, Home Assistant asks for the node's web password (`--webpwd`), used to
read and switch node settings and to read firmware and battery voltage.
Leave it empty if the node has none (not recommended, see
[Security](#security)). Both passwords can be changed later under
**Reconfigure**; if the node rejects one, Home Assistant asks for it
(reauthentication).

### Options

| Option | Meaning |
| --- | --- |
| Groups | Group numbers for the group select, in addition to the node's own groups |
| Other users who may send | Non-admin users released for sending and for the MeshCom panel |
| Chat: only own groups | On by default: messages to groups the node does not listen to stay out of the chat (events still fire) |
| Stations | Off / Data only (default) / One device per station |
| Maximum station devices | Default 50 |
| Remove station devices after (days) | Default 7 |

Changing the options reloads the node.

## What you get

### Entities of the own node

| Entity | Notes |
| --- | --- |
| Battery, Altitude | From the node's beacon; altitude disabled by default |
| Battery voltage | From the node's info page (web password needed if one is set); unknown on USB power |
| Last message, Last sender, Last message time | Messages to you, your groups and to all; kept over a restart |
| Messages received, Messages sent | Counters; continue over a restart |
| Stations heard (24 h) | In "data only" mode with the list attribute `stations` |
| Last RSSI, Last SNR | Signal of the last message (unknown if it came via the server); disabled by default |
| Firmware | From the node's beacon (UDP) or its info page (KISS) |
| Temperature, humidity, pressure, CO2 | Only if the node reports sensor values |
| Active (binary sensor) | On while the node sends packets |
| KISS connected (binary sensor) | KISS access only |
| Position (device tracker) | Position of the node's beacon |
| Recipient type, Group, Station (selects), Message (text), Send, Clear (buttons) | Compose and send from a dashboard |
| Allow sending (switch) | Kill switch: off blocks every transmission through this node |
| No MSG All (switch) | The node's setting, read and written via the web API |

### Heard stations

| Mode | What you get |
| --- | --- |
| Off | Only the count and the station select for direct messages |
| Data only (default) | The attribute `stations` of "Stations heard": the 100 most recently heard stations with last heard, RSSI, SNR, hops, battery and position. Not written to the database. |
| One device per station | A device per station (behind the own node) with position, last heard, battery, RSSI, SNR and hops. Limited in number; removed after the configured days without a packet and back when heard again; can be deleted by hand. |

The station list is stored and survives a restart.

### MeshCom panel

The sidebar entry **MeshCom** opens a panel with three tabs. With several
nodes, a selector at the top switches between them; the panel remembers the
selected node and tab per browser.

**Chat**: a conversation for messages to all, for every group and every
direct-message partner, plus read-only conversations for other addressees
(e.g. `TEST`). Filters: All, Unread, DMs, Groups (including the broadcast channel "All"), Other. Each message shows
time, path (`via DJ6PT-2 > DB0HOB-12`) and RSSI/SNR. Conversations with new
messages show a badge with their number (read state is kept per browser);
when you open one, it starts at a "New messages" line, and a button jumps to
the newest message. Delivery of your direct messages is shown (sent,
delivered, rejected). The last 500 messages per node are stored.

**Nodes**: one card per own node with access, status, battery, firmware,
stations, signal values and the switches "Allow sending" and "No MSG All".
The switches use the normal Home Assistant services, so only administrators
can change them.

**Stations**: a map with your node and every station that sent a position
(green: heard within the last hour, orange: within 24 hours, grey: older;
a legend on the map explains the colours),
and below it the heard stations as a sortable table. A click on a station on
the map shows its values with buttons for a direct message and for
OpenStreetMap. In the table, a click on a callsign zooms the map to that
station (as does "Map"), and "(DM)" behind the callsign opens a direct
message.

The map tiles are loaded from OpenStreetMap (`tile.openstreetmap.org`) only
while the Stations tab is open, so the OpenStreetMap servers see your IP
address and the map area you look at. The panel itself loads no other code
from outside. With the station mode "One device per station" the stations
also appear on the Home Assistant map.

Administrators and the users released in the options may use the panel.

### No MSG All and the message filter

While **No MSG All** is on, Home Assistant shows what the node's display
shows: messages to your groups and direct messages to you. Messages to all,
to other groups and other addressees create no event, do not change the
"last message" sensors and do not appear in the chat; the senders still
count as heard stations.

### Who may send

- Administrators, and users released in the options. Automations may send.
- At most 3 messages in a row, then one every 30 seconds, for the whole
  Home Assistant instance.
- **Allow sending** off blocks everything for that node.
- Every transmission appears in the logbook with the user or automation.

## Actions and events

### Action `meshcom.send_message`

| Field | Meaning |
| --- | --- |
| `config_entry_id` | The node to send through |
| `destination` | `*` (all), a group number (`262`) or a callsign (`QX1YZ-12`) |
| `message` | Text, at most 150 bytes, no line breaks or control characters |

Texts that look like protocol control traffic (`{CET}…`, `RM1 …`, endings
like `:ack12` or `{123`) are refused.

### Events

| Event | Fired for |
| --- | --- |
| `meshcom_message` | Every received or own text message (`sender`, `destination`, `destination_kind`, `text`, `to_me`, `is_own`, `via_server`, `path`, `rssi`, `snr`, `msg_id`) |
| `meshcom_message_sent` | A message sent from Home Assistant (with the context of the user or automation) |
| `meshcom_delivery_update` | Delivery status of your own messages (`msg_id`, `status`, `from`) |

Message text is untrusted data from the radio. Use it as data only; never
feed it into templates that are executed, commands or scripts.

## Data updates

- **UDP and KISS are push:** every packet updates the entities immediately.
- **Web API** (No MSG All, groups, firmware, battery voltage): read every
  5 minutes with one login, and right after a change from Home Assistant.
- "Active" turns off when the node sent nothing for 65 minutes (beacons
  come every 30 minutes by default).

## Examples

Notify on a direct message to you:

```yaml
automation:
  - alias: MeshCom direct message
    triggers:
      - trigger: event
        event_type: meshcom_message
        event_data:
          destination_kind: direct
          to_me: true
    actions:
      - action: notify.mobile_app_phone
        data:
          title: "MeshCom from {{ trigger.event.data.sender }}"
          message: "{{ trigger.event.data.text }}"
```

Send a daily message to a group:

```yaml
automation:
  - alias: MeshCom good morning
    triggers:
      - trigger: time
        at: "07:30:00"
    actions:
      - action: meshcom.send_message
        data:
          config_entry_id: YOUR_ENTRY_ID
          destination: "262"
          message: "Guten Morgen aus dem Shack"
```

Use cases: a chat on the wall tablet, notifications for direct messages,
presence of a mobile node ("Active"), a map of heard stations, switching
**No MSG All** at night.

## Known limitations

- **KISS:** frames carry no MeshCom message id and no firmware version, so
  the "Firmware" sensor stays empty and the node id is derived from the
  callsign. The node serves one KISS client at a time; Home Assistant keeps
  that slot. RSSI/SNR are those of the last hop and need `--kiss meta on`.
- **Firmware 4.34z–4.40a web login** is plain text (see [Security](#security)).
- Direct messages between other stations are passed on as events but not
  counted and not shown in the chat.
- A temperature of exactly 0.0 °C is reported as unknown (the node sends 0
  for "no value").
- HACS installs releases, not the newest commit.

## Troubleshooting

| Problem | What to check |
| --- | --- |
| "No packet from the node" during setup | ext UDP on, ext. UDP IP = Home Assistant, then "Send Position" |
| "The node's web interface cannot be reached" | IP address; firmware 4.34z or newer |
| Warning "uses the unencrypted web login" | Expected with firmware up to 4.40a; disappears after an update with the secure login |
| "KISS interface cannot be reached" | `--kiss on`, port 8001, no other KISS client connected |
| Warning "KISS interface without authentication" | Set `--passwd` and `--kiss auth on`, then Reconfigure |
| Sending fails with "does not allow sending via KISS" | `--kiss tx on` |
| MeshCom panel is empty | User is neither administrator nor released in the options |
| No icon | Home Assistant 2026.3 or newer needed |

Debug logging:

```yaml
logger:
  logs:
    custom_components.meshcom: debug
```

Diagnostics (device page → Download diagnostics) contain no addresses,
callsigns, positions, message text or passwords and can be attached to an
issue.

## Removal

1. **Settings → Devices & services → MeshCom → ⋮ → Delete** for each node.
   The stored station list and chat history are deleted with it.
2. Uninstall in HACS (or delete `custom_components/meshcom`) and restart.
3. On the node, switch off what you enabled for Home Assistant: ext UDP
   (`--extudp off`) or KISS (`--kiss off`).

## Security

Everything received from the mesh is treated as untrusted data. Transmitting
is restricted to administrators by default. See [SECURITY.md](SECURITY.md)
for the security policy and how to report a vulnerability.

Recommended node settings:

- Set a **web password** on every node (`--webpwd`, up to 19 characters).
  Without it, every device and every browser on your network can read the
  node's WLAN password.
- Firmware 4.34z to 4.40a send the web password unencrypted and then trust
  the client's IP address for 4 hours. Home Assistant logs out right after
  every query and switches to the secure nonce/HMAC login as soon as the
  node offers it, never back.
- Only enable **ext UDP** on nodes that stay in your home network; the
  interface accepts commands from any device on that network.
- For **KISS**, always use `--kiss auth on` with `--passwd`.

## Development

| Path | Content |
| --- | --- |
| `custom_components/meshcom/` | The Home Assistant integration |
| `custom_components/meshcom/aiomeshcom/` | Protocol library (asyncio, no Home Assistant dependency) |
| `custom_components/meshcom/frontend/` | MeshCom panel: chat, nodes, stations (plain web component) |
| `tests/lib/` | Library tests, including anonymised real-world packets |
| `tests/integration/` | Home Assistant integration tests |
| `tools/` | Capture anonymiser, brand icon source |
| `tools/screenshots/` | Demo data and script for the panel screenshots in `docs/images/` (invented data only) |
| `docs/images/` | Screenshots used in this README |

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[test]"
pytest                      # library tests
ruff check . && ruff format --check .
mypy                        # library types

# Home Assistant integration tests (separate environment)
pip install "pytest-homeassistant-custom-component==0.13.316" pytest-cov
pytest tests/integration -o addopts="" -o asyncio_mode=auto \
  --cov --cov-config=tests/integration/.coveragerc
mypy --config-file tests/integration/mypy.ini custom_components/meshcom tests/integration
```

A new version in `manifest.json` together with a section in `CHANGELOG.md`
creates the release when it reaches `main`.

## License

[MIT](LICENSE)

MeshCom is a project of [ICSSW](https://icssw.org). This integration is an
independent community project and not affiliated with ICSSW.
