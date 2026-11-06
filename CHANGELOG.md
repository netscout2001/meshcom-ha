# Changelog

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
