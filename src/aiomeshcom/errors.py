"""Exceptions raised by aiomeshcom."""

from __future__ import annotations


class MeshComError(Exception):
    """Base class for all aiomeshcom errors."""


class InvalidPacketError(MeshComError):
    """A received datagram was rejected.

    ``reason`` is a short, stable code that is safe to log and to count. It
    never contains data from the packet itself, so a hostile packet cannot
    inject text into logs through the exception message.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(f"invalid packet: {reason}")
        self.reason = reason


class InvalidOutgoingError(MeshComError):
    """Data meant for the node failed validation and was not sent."""

    def __init__(self, reason: str) -> None:
        super().__init__(f"invalid outgoing data: {reason}")
        self.reason = reason
