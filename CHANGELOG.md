# Changelog

## v0.5.1

### Fixes
- Chat filters: the open conversation no longer stays in every filter (e.g. "All" under "DMs"); it only stays while it was opened from the current filter. "All" belongs to "Groups" as the broadcast channel.

### Features
- Stations tab: hint that the station mode "One device per station" shows the stations on the Home Assistant map

## v0.5.0

### Features
- MeshCom panel with the tabs Chat, Nodes and Stations
- Chat: filters All / Unread / DMs / Groups / Other and a coloured symbol per conversation
- Chat: the path of a message is shown in its header ("via DJ6PT-2 > DB0HOB-12")
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
