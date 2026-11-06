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

## Repository layout

| Path | Content |
| --- | --- |
| `src/aiomeshcom/` | Protocol library (asyncio, no Home Assistant dependency) |
| `tests/` | Tests for the library, including anonymised real-world packets |
| `custom_components/meshcom/` | The Home Assistant integration (coming in phase 1) |

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
pytest
ruff check . && ruff format --check .
mypy
```

## License

[MIT](LICENSE)

MeshCom is a project of [ICSSW](https://icssw.org). This integration is an
independent community project and not affiliated with ICSSW.
