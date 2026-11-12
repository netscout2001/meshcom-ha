# Security Policy

## Supported versions

meshcom-ha is in early development. Security fixes are applied to the latest
release only.

| Version        | Supported |
| -------------- | --------- |
| Latest release | Yes       |
| Older releases | No        |

## Reporting a vulnerability

Please report vulnerabilities **privately**. Do **not** open a public issue.

1. Open the **Security** tab of this repository.
2. Click **Report a vulnerability**.
3. Describe the issue, the affected version and the steps to reproduce.

You will get an acknowledgement within 7 days. A fix is coordinated and
released before details are published. Credit is given if you want it.

## Scope

In scope:

- Handling of untrusted data received from the MeshCom network (radio and
  MeshCom server): callsigns, message text, positions, telemetry.
- Rendering of that data in the Home Assistant frontend (chat panel, cards).
- Authorization of services and WebSocket commands (who may transmit, who may
  change node settings).
- Handling of node credentials (web password, console password).

Out of scope (please report to the respective project):

- Vulnerabilities in the MeshCom firmware itself:
  <https://github.com/icssw-org/MeshCom-Firmware>
- Vulnerabilities in Home Assistant Core or Home Assistant OS.

## Design principles

- Everything received from the mesh is untrusted data, never code or markup.
- MeshCom's external UDP interface has no authentication. Any device on the
  LAN can send packets to Home Assistant and to the node. The integration
  validates every packet strictly, but it cannot prove who sent it.
- Transmitting on amateur radio is restricted to administrators by default.
- A firmware update is only started on request (Install) and only by
  administrators or automations. Home Assistant never chooses the image: the
  node downloads the release it found on the firmware project's release page
  and checks it itself. The integration can call only the two update steps
  (download, install) and no other node function.
- Node secrets (WLAN password, web password, BT PIN) are never read, logged or
  included in diagnostics.
