"""Constants of the MeshCom external UDP interface.

Values are taken from the MeshCom firmware source (v4.40a), not from the
public documentation, where the two disagree.
"""

from __future__ import annotations

from typing import Final

#: The node sends to and listens on this port. The destination port of the
#: node's outgoing datagrams is fixed (``EXTERN_PORT`` in the firmware).
EXT_UDP_PORT: Final = 1799

#: Upper bound for a datagram we accept. Real packets are about 400 bytes.
#: Anything larger is rejected before it is decoded.
MAX_DATAGRAM_BYTES: Final = 1024

#: The node reads at most this many bytes of an incoming datagram
#: (``UDP_TX_BUF_SIZE - 1``). Larger outgoing datagrams would be cut.
NODE_MAX_INCOMING_BYTES: Final = 254

#: The node checks the message text with ``strlen()``, i.e. in UTF-8 bytes.
MAX_OUTGOING_TEXT_BYTES: Final = 150

#: Longest message text we accept from the mesh (``MC_PAYLOAD_LEN``).
MAX_INCOMING_TEXT_CHARS: Final = 256

#: Longest source path string (``MC_PATH_LEN``).
MAX_PATH_CHARS: Final = 121

#: Longest destination (callsign incl. SSID or group number).
MAX_DESTINATION_CHARS: Final = 9

#: Upper bound for the number of keys in one JSON object.
MAX_JSON_KEYS: Final = 40

#: Altitude is transmitted in feet (APRS convention).
FEET_TO_METERS: Final = 0.3048

#: Web API parameters that return secrets in clear text. The library never
#: requests them (security concept C-04).
SECRET_WEB_PARAMETERS: Final = frozenset({"setpwd", "setssid", "webpwd", "passwd"})

#: Prefix of the time beacons sent by the MeshCom servers.
TIME_BEACON_PREFIX: Final = "{CET}"
