# MeshCom for Home Assistant

> **Status: early development – not ready for use.**

A Home Assistant integration for the [MeshCom](https://icssw.org/en/meshcom/)
LoRa mesh network (433 MHz amateur radio).

Planned features:

- Sensors, buttons and device trackers for your own MeshCom nodes
- Heard stations as devices or as plain data (configurable)
- Sending and receiving messages: broadcast, groups and direct messages,
  with delivery status
- Support for several nodes at once
- Access via the node's external UDP interface, the web API (with or without
  web password) and the NET console

## Current state

- One config entry per node; several nodes share one UDP port
- Sensors: battery, last message, last sender, message counters, stations
  heard in the last 24 h, firmware, RSSI/SNR (disabled by default), and
  environment sensors if the node reports them
- Binary sensor "Active" and a device tracker for the node's position
- Events `meshcom_message`, `meshcom_message_sent` and
  `meshcom_delivery_update` (only for acknowledgements of your own messages)
- Sending: recipient type, group and station selects, a message text field,
  send and clear buttons, and the action `meshcom.send_message`
- Web API (optional web password): the switch **No MSG All** shows and sets
  the node's setting of the same name, and the group select offers the
  node's groups. The node is read every 5 minutes with one login.
- Diagnostics without addresses, positions, message text or passwords

The NET console may follow as an option.

### Access path: external UDP or KISS over TCP

When adding a node you choose how Home Assistant reaches it:

- **External UDP** for nodes in the home network: the node sends every
  packet to Home Assistant (`--extudpip`, `--extudp on`).
- **KISS over TCP** (port 8001), e.g. for a mobile node whose external UDP
  should stay off: enable `--kiss on`, for sending `--kiss tx on`, and
  protect it with `--kiss auth on` and the node password `--passwd` (up to
  14 characters). Without authentication anyone in the network can connect
  and transmit under your callsign; Home Assistant shows a repair warning.

Notes on KISS:

- The node serves one KISS client at a time. Home Assistant keeps the
  connection open and reconnects on its own (a mobile node out of reach is
  normal); the binary sensor **KISS connected** shows the state.
- KISS frames carry no MeshCom message id and no firmware version, so the
  "Firmware" sensor stays empty and the node id is derived from the
  callsign.
- RSSI/SNR need `--kiss meta on`; stations with an SSID above 15 are shown
  with their full callsign.
- A rejected node password starts reauthentication; Home Assistant does
  not retry with a wrong password.

### Chat panel

The sidebar entry **MeshCom** opens a chat with one conversation each for
messages to all, every group and every direct-message partner (plus
read-only conversations for messages to other addressees, e.g. `TEST`).
Delivery of own direct messages is shown (sent, delivered, rejected).

- Readable by administrators and by the users released for sending in the
  node's options; other users get nothing.
- Sending uses the same checks as the action `meshcom.send_message`: the
  "Allow sending" switch, the permission, the validation of the text and
  the rate limit.
- While **No MSG All** is on, the chat shows only what the node shows.
- The last 500 messages per node are stored and survive a restart.
- Message text is shown as plain text only. The panel never interprets
  it as HTML and never turns it into links.

### Heard stations

The options decide how heard stations appear:

| Mode | What you get |
| --- | --- |
| Off | Only the count "Stations heard (24 h)" and the station select for direct messages |
| Data only (default) | Additionally the attribute `stations` of that sensor: the 100 most recently heard stations with last heard, RSSI, SNR, hops, battery and position. The attribute is not written to the database. |
| One device per station | A device per station (behind the own node) with position, last heard, battery, RSSI, SNR and hops. At most 50 devices (adjustable); a device is removed after 7 days without a packet (adjustable) and comes back when the station is heard again. Station devices can also be deleted by hand. |

The station list is stored, so it survives a restart.

### No MSG All and the message filter

While **No MSG All** is on, Home Assistant shows the same messages as the
node's display: messages to the node's own groups and direct messages to
the node. Messages to all (`*`), to other groups and to other addressees
create no event and do not change the "last message" sensors; the senders
are still counted as heard stations. Only administrators (and automations)
may change the switch. If the node rejects the stored password, Home
Assistant asks for the new one (reauthentication); the password can also be
changed under **Reconfigure**. A node without a web password gets a repair
hint.

### Web login and firmware 4.40a

Firmware 4.40a only has a plain-text web login: the password travels
unencrypted in the URL, and the node then trusts the client's IP address
for 4 hours. Home Assistant uses it only if the node offers nothing better,
logs out right after every query (every 5 minutes) so the trust lasts
seconds, and shows a repair warning. Newer firmware has a nonce/HMAC login
where the password never travels. Home Assistant switches to it by itself
as soon as the node offers it and from then on never uses the plain-text
login for that node again (protection against downgrades and impostors).

### Who may send

Everything sent goes out on amateur radio under the node's callsign.

- Administrators may send. Other users only if released in the options.
- Automations may send (they are configured by an administrator).
- At most 3 messages in a row, then one every 30 seconds, for the whole
  Home Assistant instance.
- The switch **Allow sending** blocks sending through a node completely.
- Every transmission appears in the logbook with the user or automation that
  triggered it.

## Installation (manual, for testing)

1. Copy `custom_components/meshcom` into the `custom_components` folder of
   your Home Assistant configuration and restart Home Assistant.
2. On the node, set **ext. UDP IP** to the IP address of Home Assistant and
   enable **ext UDP**.
3. In Home Assistant go to **Settings → Devices & services → Add integration
   → MeshCom** and enter the node's IP address.
4. While Home Assistant waits, click **Send Position** on the node's web page.
5. Enter the node's web password, or leave it empty if the node has none.

## Repository layout

| Path | Content |
| --- | --- |
| `custom_components/meshcom/` | The Home Assistant integration |
| `custom_components/meshcom/aiomeshcom/` | Protocol library (asyncio, no Home Assistant dependency) |
| `tests/lib/` | Library tests, including anonymised real-world packets |
| `tests/integration/` | Home Assistant integration tests |
| `tools/` | Helper scripts (capture anonymiser) |

## Security

Everything received from the mesh is treated as untrusted data. Transmitting
is restricted to administrators by default. See [SECURITY.md](SECURITY.md)
for the security policy and how to report a vulnerability.

### Recommended node settings

- Set a **web password** on every node (`--webpwd <password>`, up to 19
  characters). Without it, the node's web API is open to every device and
  every browser on your network.
- Only enable the external UDP interface on nodes that stay in your home
  network. The interface accepts commands from any device on the network the
  node is connected to.

## Development

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

## License

[MIT](LICENSE)

MeshCom is a project of [ICSSW](https://icssw.org). This integration is an
independent community project and not affiliated with ICSSW.
