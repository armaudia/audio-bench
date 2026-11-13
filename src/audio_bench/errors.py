"""Typed errors with stable machine-readable reasons."""

from __future__ import annotations


class BenchError(Exception):
    """Base class for expected, reportable failures."""


class ValidationError(BenchError):
    """A record, bundle or fixture violates the evidence specification."""

    def __init__(self, message: str, *, path: str | None = None) -> None:
        super().__init__(message if path is None else f"{path}: {message}")
        self.message = message
        self.path = path


class InvocationError(BenchError):
    """Bad command line / API invocation (CLI exit code 2, not a bundle verdict)."""


class BlockedError(BenchError):
    """A named prerequisite is unavailable; the associated claim is excluded."""

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(f"{reason}: {detail}")
        self.reason = reason
        self.detail = detail


class ImmutableViolation(ValidationError):
    """An attempt was made to change bytes that already exist under a digest path."""


class AcquisitionError(BenchError):
    """Unsafe or unverifiable acquisition input."""
