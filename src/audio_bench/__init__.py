"""audio-bench: reproducible evaluation harness for the audio SDK benchmark platform.

The package implements the normative evidence specification in ``EVIDENCE_SPEC.md``:
strict ingestion, RFC 8785 identities, immutable sealed cores, safe export and an offline
static report. It never executes candidate code while validating or reporting.
"""

__all__ = ["__version__"]

__version__ = "0.1.0"
