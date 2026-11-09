"""Anonymise a MeshCom external UDP capture before it becomes a test fixture.

Captures contain callsigns, positions, message ids derived from MAC
addresses, IP addresses and messages of other radio amateurs. None of that
may enter the public repository. This tool replaces them consistently, so
the structure (paths, acknowledgements, sequence numbers) stays intact:

* base callsigns -> placeholders (SSID kept), e.g. QL1AAA-2 -> TST1-2
* positions -> synthetic coordinates
* upper 22 bits of message ids (node id) -> synthetic node id, counter kept
* IP addresses -> documentation ranges (RFC 5737)
* free text of other stations -> placeholder text

Usage: python tools/anonymize_capture.py <capture.jsonl> <output.anon.jsonl>
       [--own BASECALL ...]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

_CALL_RE = re.compile(r"\b([A-Z0-9]{3,7})(-[0-9]{1,2})?\b")
_ACK_RE = re.compile(r"([A-Z0-9-]{1,9}) *:(ack|rej)([0-9]{1,3})")
_TAG_RE = re.compile(r"\b[0-9a-f]{16}\b")
_SEQ_RE = re.compile(r"\{[0-9]{1,3}\}?\Z")


class Anonymizer:
    """Keeps the replacement tables so mappings stay consistent per capture."""

    def __init__(self, own_calls: set[str]) -> None:
        self._own = own_calls
        self._calls: dict[str, str] = {}
        self._nodes: dict[int, int] = {}
        self._ips: dict[str, str] = {}
        self._positions = 0
        self._texts = 0

    def base_call(self, base: str) -> str:
        if base not in self._calls:
            if base in self._own:
                prefix = "OWN"
                number = sum(1 for v in self._calls.values() if v.startswith("OWN")) + 1
            else:
                prefix = "TST"
                number = sum(1 for v in self._calls.values() if v.startswith("TST")) + 1
            self._calls[base] = f"{prefix}{number}"
        return self._calls[base]

    def callsign(self, value: str) -> str:
        base, _, ssid = value.partition("-")
        return self.base_call(base) + (f"-{ssid}" if ssid else "")

    def path(self, value: str) -> str:
        return ",".join(self.callsign(part) for part in value.split(","))

    def msg_id(self, value: str) -> str:
        number = int(value, 16)
        node = number >> 10
        if node not in self._nodes:
            self._nodes[node] = 0x100000 + len(self._nodes)
        return f"{(self._nodes[node] << 10) | (number & 0x3FF):08X}"

    def ip(self, value: str) -> str:
        if value == "127.0.0.1":
            return value
        if value not in self._ips:
            self._ips[value] = f"192.0.2.{len(self._ips) + 15}"
        return self._ips[value]

    def text(self, value: str, *, own: bool, destination: str) -> str:
        if value.startswith("{CET}"):
            return value
        if value.startswith("RM1 "):
            # Remote management carries HMAC tags over known text. Published
            # tags would allow offline guessing of the node password.
            return _TAG_RE.sub("0" * 16, value)
        ack = _ACK_RE.fullmatch(value)
        if ack is not None:
            call = self.callsign(ack.group(1))
            return f"{call:<9}:{ack.group(2)}{ack.group(3)}"
        seq = _SEQ_RE.search(value)
        suffix = seq.group(0) if seq else ""
        body = value[: seq.start()] if seq else value
        if not own:
            self._texts += 1
            body = f"Sample text {self._texts}"
        del destination
        return body + suffix

    def position(self) -> tuple[float, float]:
        self._positions += 1
        return 50.0 + self._positions * 0.01, 8.0 + self._positions * 0.01

    def packet(self, raw: dict[str, Any]) -> dict[str, Any]:
        out = dict(raw)
        own = False
        if isinstance(out.get("src"), str):
            own = out["src"].split(",")[0].partition("-")[0] in self._own
            out["src"] = self.path(out["src"])
        # Group numbers ("26298") are not personal data and stay unchanged.
        dst = out.get("dst")
        is_call = isinstance(dst, str) and any(c.isdigit() for c in dst) and not dst.isdigit()
        if is_call and _CALL_RE.fullmatch(dst):
            out["dst"] = self.callsign(out["dst"])
        if isinstance(out.get("from"), str):
            out["from"] = self.callsign(out["from"])
        if isinstance(out.get("msg_id"), str):
            out["msg_id"] = self.msg_id(out["msg_id"])
        if out.get("type") == "pos" and "lat" in out:
            out["lat"], out["long"] = self.position()
        if out.get("type") == "msg" and isinstance(out.get("msg"), str):
            out["msg"] = self.text(out["msg"], own=own, destination=out.get("dst", ""))
        return out


def anonymize(lines: list[str], own_calls: set[str]) -> list[str]:
    anonymizer = Anonymizer(own_calls)
    result = []
    for line in lines:
        if not line.strip().startswith("{"):
            continue
        record = json.loads(line)
        record["src"] = anonymizer.ip(record["src"])
        try:
            packet = json.loads(record["raw"])
        except ValueError:
            packet = None
        if isinstance(packet, dict) and "type" in packet:
            record["raw"] = json.dumps(
                anonymizer.packet(packet), ensure_ascii=False, separators=(",", ":")
            )
        result.append(json.dumps(record, ensure_ascii=False))
    return result


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("capture", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--own", nargs="*", default=[], help="own base callsigns")
    args = parser.parse_args(argv)
    lines = args.capture.read_text(encoding="utf-8").splitlines()
    output = anonymize(lines, set(args.own))
    args.output.write_text("\n".join(output) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
