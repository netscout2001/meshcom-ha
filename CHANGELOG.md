# Changelog

## v0.7.2

Result of an independent security review of the code and of permanent fuzz
tests. No critical or high findings.

### Security
- "Allow sending": anyone may switch it off, but only administrators may switch it back on (before, any user with control rights could undo an administrator's kill switch)
- Draft entities (recipient type, group, station, message text, Clear): only users who may send can change them
- Invisible characters in received text are removed more thoroughly: all format characters (including the invisible tag characters U+E0000-E007F and the soft hyphen), line and paragraph separators and the blank Hangul filler letters
- The web API is not polled while the node is inactive: no logins at an address that may meanwhile belong to another device; polling resumes as soon as the node is heard
- README: further remaining risks (forged UDP flood, forgeable delivery confirmations, own callsign over KISS, offline guessing of weak web passwords, entity states readable by all users)

### Fixes
- Blueprint "notify with reply": a reply that looks like a list or a dictionary (e.g. `[1, 2]`) failed to send; the reply is now always passed on as text. Re-import the blueprint to get the fix.
- Chat history: a stored entry with a malformed delivery status no longer breaks loading (found by fuzzing)

### Development
- Property-based fuzz tests (Hypothesis) for every parser of untrusted input: datagrams, KISS frames, web API answers, station and chat storage; deterministic on pull requests, a weekly run searches randomly and longer
- CodeQL now also scans the panel's JavaScript

## v0.7.1

### Fixes
- Blueprint "notify with reply": radio text such as `[1, 2]`, `{'a': 1}` or `True` was turned into a list, dictionary or boolean by Home Assistant's template typing; the notification now shows "sender: text" and the conversation in the title (`MeshCom · DM`, `MeshCom · 262`). Re-import the blueprint to get the fix. The README example is fixed the same way.

### Changes
- Test data, demo data and the map's default centre use an invented area instead of coordinates in a real region
- README: remaining security risks (unauthenticated external UDP, automations send without the per-user check, map tiles)

## v0.7.0

### Features
- Blueprint "MeshCom – notify with reply": push notification for direct messages (and optionally chosen groups and messages to all) with a Reply button that answers into the same conversation
- Sensor "Last packet" (time of the node's last packet), kept over a restart; "Active" is now right right after a restart too
- Option "Node inactive after (minutes)" (default 65) for "Active"
- Weather values of other stations (temperature, humidity, air pressure QNH/QFE) from their telemetry, also over KISS: in the station table and on the map; in the mode "One device per station" as sensors of stations that send them
- Radio path: the relays of each station's last packet are kept; on the map a selected station shows its path to the own node as a line (dashed across relays without a known position); a click on a message's path in the chat shows it on the map

### Changes
- Example callsigns in README and tests use the unassigned prefix `Q`
- Test data no longer contains the exact position of a real node

## v0.6.1

### Changes
- Examples in the setup texts, README, code comments and tests use the neutral callsign `QX1YZ` (prefix `Q` is not assigned to any country) instead of a real one
- README: screenshots of the Stations tab with the map

## v0.6.0

### Migration
- Node id: derived from the callsign for both access paths (before: the hardware id for UDP, the callsign for KISS). Existing entries are migrated automatically; entity ids, history and entity settings stay. A node moved from KISS to UDP or back keeps its device and entities.

### Features
- Battery voltage sensor, read from the node's info page via the web API (unknown on USB power)
- Firmware for KISS nodes, read from the node's info page (KISS frames carry no version)
- "Last message", "Last sender" and "Last message received" keep their value over a restart; "Messages received/sent" continue counting instead of starting at 0
- README: screenshots (made from invented data)

### Changes
- "Last RSSI" and "Last SNR" now belong to the last message (unknown if it came via the server); before, they followed every packet, also beacons of other stations
- README: installation via HACS search first, custom repository as the fallback

### Security
- Diagnostics no longer contain the node's callsign or node id: a callsign identifies the licence holder in public registries (HACS review)

## v0.5.5

### Fixes
- Panel: switching to another node no longer shows the conversation that was open on the previous node (e.g. a direct message to your own callsign); the other node starts at "All"
- Position of the own node: after a restart the last known position is kept until the node sends its next beacon (the sensors already did this); before, the tracker and the own marker on the map were unknown for several minutes

### Changes
- Panel: the selected node and tab are remembered per browser, a reload opens the same view

## v0.5.4

### Changes
- Stations table: a click on a callsign zooms the map to the station; "(DM)" behind the callsign opens the direct message

### Fixes
- Stations map: no more thin light lines between the map tiles (tiles on whole pixels with 1 px overlap, dark background in dark mode)

## v0.5.3

### Features
- Stations map: legend for the marker colours (own node, < 1 h, < 24 h, older)

## v0.5.2

### Features
- Stations tab: map with the own node and all stations that sent a position (OpenStreetMap tiles, colour by last heard, zoom, drag, popup with direct message). "Map" in the table now shows the station on this map. The map is part of the panel; no external script is loaded, the tiles are loaded only while the tab is open.

### Changes
- Stations tab: the hint about the Home Assistant map is removed

## v0.5.1

### Fixes
- Chat filters: the open conversation no longer stays in every filter (e.g. "All" under "DMs"); it only stays while it was opened from the current filter. "All" belongs to "Groups" as the broadcast channel.

### Features
- Stations tab: hint that the station mode "One device per station" shows the stations on the Home Assistant map

## v0.5.0

### Features
- MeshCom panel with the tabs Chat, Nodes and Stations
- Chat: filters All / Unread / DMs / Groups / Other and a coloured symbol per conversation
- Chat: the path of a message is shown in its header ("via QR1ABC-2 > QB0RLY-12")
- Chat: a "New messages" line marks the first unread message; opening a conversation starts there, a button jumps to the newest message
- Chat: only the messages scroll; the conversation list stays in place
- Nodes: one card per own node with status, sensors and the switches "Allow sending" and "No MSG All"
- Stations: sortable table of heard stations; a click opens a direct message, "Map" opens the position on OpenStreetMap
- Signal values and hops of a station are also updated from its messages, not only from positions

## v0.4.6

### Maintenance
- HACS validation runs without any ignored checks (brands, topics), as required for the HACS default repositories

## v0.4.5

### Fixes
- Several nodes starting at the same time no longer register the chat panel twice ("Overwriting panel meshcom-chat"). This race was also the cause of the earlier "already been setup" errors.

## v0.4.4

### Fixes
- Setup: the chat panel is registered before the platforms, and a panel error no longer stops the node. Before, an error after the platforms had started left them loaded, and the next reload failed with "already been setup".

## v0.4.3

### Features
- Option "Chat: only own groups" (on by default): the chat no longer shows messages to groups the node does not listen to; groups from the options count as own. External UDP delivers all mesh traffic, so foreign groups used to get their own conversation. Events and sensors are unchanged.

## v0.4.2

### Features
- Chat panel: conversations with unread messages show a coloured badge with the number of new messages and a bold title; read state is remembered per browser

## v0.4.1

### Fixes
- KISS nodes: the "Firmware" sensor and the device stay without a version instead of showing "unknown" (KISS frames carry no firmware version)

### Documentation
- README rewritten: supported devices, installation via HACS, configuration fields and options, entities, actions and events, data updates, examples, known limitations, troubleshooting and removal

## v0.4.0

### Features
- Second access path per node: KISS over TCP (firmware 4.40a), selectable when adding a node; for nodes whose external UDP stays off, e.g. a mobile node
- Optional KISS authentication (HMAC-SHA256 with the node password), reauthentication when the node rejects it, repair warning when the node does not ask for a password
- Receiving positions, messages and acknowledgements via KISS, including RSSI/SNR and full callsigns of stations with an SSID above 15; sending via KISS with delivery tracking
- Binary sensor "KISS connected"; automatic reconnect

### Security
- KISS frames go through the same validation as UDP datagrams; a frame with the node's callsign but a measured RSSI is not treated as the node's own

## v0.3.0

### Features
- Chat panel "MeshCom" in the sidebar: conversations for all, groups, direct messages and other addressees, live updates and delivery status of own direct messages
- Chat history (last 500 messages per node) is stored and survives a restart
- Reading is limited to administrators and users released for sending; sending uses the same checks as `meshcom.send_message`

### Security
- The panel renders message text as plain text only; a test checks the panel for HTML sinks

## v0.2.0

### Features
- Station mode in the options: off, data only (list attribute of "Stations heard", default) or one device per station with position, last heard, battery, RSSI, SNR and hops
- Station devices appear automatically, are limited (default 50) and are removed after a number of days without a packet (default 7); they can also be deleted by hand
- The station list is stored and survives a restart
- Changing the options reloads the node

## v0.1.0

First release of the MeshCom integration for Home Assistant.

### Features
- Receives position, telemetry and messages from a MeshCom node via its external UDP interface (several nodes share one port)
- Sensors: battery, last message and sender, message counters, stations heard in 24 h, firmware, RSSI/SNR, environment sensors
- Binary sensor "Active" and a device tracker for the node position
- Sending: recipient, group and station selects, message text, send and clear buttons, action `meshcom.send_message`, delivery tracking by acknowledgement
- Switch "Allow sending" (kill switch); sending reserved for administrators unless released in the options; rate limit
- Web API: switch "No MSG All" with a matching message filter in Home Assistant, the node's groups in the group select
- Web login: secure nonce/HMAC login where the firmware offers it; plain-text login of firmware 4.34z to 4.40a with immediate logout and a repair warning; once the secure login was used it is pinned (no downgrade)
- Reauthentication, reconfiguration, repair hints, diagnostics without addresses, positions, message text or passwords
- Own brand icon (Home Assistant 2026.3 or newer)

### Requirements
- Home Assistant 2025.6 or newer
- MeshCom firmware 4.34z or newer for the web functions

See the README for installation and the recommended node settings.
