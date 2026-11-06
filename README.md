# MeshCom for Home Assistant

> **Status: early development – not ready for use.**

A Home Assistant integration for the [MeshCom](https://icssw.org/en/meshcom/)
LoRa mesh network (433 MHz amateur radio).

Planned features:

- Sensors, buttons and device trackers for your own MeshCom nodes
- Heard stations as devices or as plain data (configurable)
- Sending and receiving messages: broadcast, groups and direct messages,
  with delivery status
- A chat panel in the Home Assistant sidebar
- Support for several nodes at once
- Access via the node's external UDP interface, the web API (with or without
  web password) and the NET console

## Current state (phase 1, receive only)

- One config entry per node; several nodes share one UDP port
- Sensors: battery, last message, last sender, message counters, stations
  heard in the last 24 h, firmware, RSSI/SNR (disabled by default), and
  environment sensors if the node reports them
- Binary sensor "Active" and a device tracker for the node's position
- Events `meshcom_message` and `meshcom_delivery_update`
- Diagnostics without addresses, positions or message text

Sending, the web API, the NET console, KISS/TCP and the chat panel follow.

## Installation (manual, for testing)

1. Copy `custom_components/meshcom` into the `custom_components` folder of
   your Home Assistant configuration and restart Home Assistant.
2. On the node, set **ext. UDP IP** to the IP address of Home Assistant and
   enable **ext UDP**.
3. In Home Assistant go to **Settings → Devices & services → Add integration
   → MeshCom** and enter the node's IP address.
4. While Home Assistant waits, click **Send Position** on the node's web page.

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
