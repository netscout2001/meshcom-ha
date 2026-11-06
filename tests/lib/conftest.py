"""Shared fixtures."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
#: Address of the (anonymised) node in the capture fixture.
NODE_ADDRESS = "192.0.2.15"


def load_capture(name: str) -> list[tuple[str, bytes]]:
    """Return (sender address, datagram) pairs of an anonymised capture."""
    records = []
    for line in (FIXTURES / name).read_text(encoding="utf-8").splitlines():
        if line.strip():
            record = json.loads(line)
            records.append((record["src"], record["raw"].encode("utf-8")))
    return records


@pytest.fixture(scope="session")
def capture() -> list[tuple[str, bytes]]:
    """Real packets from 2026-11-06, anonymised."""
    return load_capture("capture_2026-11-06.anon.jsonl")


@pytest.fixture(scope="session")
def node_packets(capture: list[tuple[str, bytes]]) -> list[bytes]:
    """Only the datagrams sent by the node."""
    return [data for address, data in capture if address == NODE_ADDRESS]
