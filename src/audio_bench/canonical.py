# SPDX-FileCopyrightText: 2026 Tsakanyan Hovhannes
# SPDX-License-Identifier: Apache-2.0
"""Strict JSON ingestion, RFC 8785 (JCS) canonicalization and content identities.

Rules implemented here (EVIDENCE_SPEC.md "Encoding and identity"):

* Control records are UTF-8 JSON with no BOM, no duplicate keys, no lone surrogates and no
  non-finite numbers. Duplicate detection happens on *decoded* keys, so ``"a"`` and ``"\\u0061"``
  collide as they must.
* Identities use RFC 8785 canonical bytes and SHA-256, rendered ``sha256:<64 lowercase hex>``.
* Every identity preimage omits the artifact's own ID field and includes ``schema_id`` plus
  ``identity_algorithm``. Nothing is re-hashed with a mutated preimage.
* The legacy research serializer (``ensure_ascii`` sorted JSON) is preserved *only* under the
  ``legacy-json-v1`` label for read-only import; its hashes are never reinterpreted.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Iterator, Mapping
from typing import Any

import rfc8785

from .errors import ValidationError

JCS_IDENTITY_ALGORITHM = "jcs-sha256-v1"
LEGACY_IDENTITY_ALGORITHM = "legacy-json-v1"

#: Largest integer that survives a round trip through an IEEE-754 double.
SAFE_INTEGER_MAX = 2**53 - 1

#: Hard cap for a single parsed control record (EVIDENCE_SPEC: <= 1 MB per record).
MAX_RECORD_BYTES = 1024 * 1024

_BOM = b"\xef\xbb\xbf"
_DIGEST_RE = re.compile(r"\Asha256:[0-9a-f]{64}\Z")
_UINT_RE = re.compile(r"\A(0|[1-9][0-9]*)\Z")
_INT_RE = re.compile(r"\A(0|-?[1-9][0-9]*)\Z")
_DECIMAL_RE = re.compile(r"\A(0|-?[1-9][0-9]*)(\.[0-9]+)?\Z")
_UINT64_MAX = 2**64 - 1
_INT64_MIN = -(2**63)
_INT64_MAX = 2**63 - 1


def _reject_constant(token: str) -> Any:
    raise ValidationError(f"non-finite JSON number: {token}")


def _pairs_no_duplicates(items: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in items:
        if key in out:
            raise ValidationError(f"duplicate object key: {key!r}")
        out[key] = value
    return out


def _has_lone_surrogate(text: str) -> bool:
    return any(0xD800 <= ord(ch) <= 0xDFFF for ch in text)


def strict_loads(payload: bytes | str, *, path: str | None = None, max_bytes: int = MAX_RECORD_BYTES) -> Any:
    """Parse JSON with the strict evidence rules.

    Accepts human-formatted source JSON (whitespace, key order, escapes) but rejects anything that
    loses information or cannot be canonicalized later: BOM, invalid UTF-8, duplicate keys,
    non-finite numbers, lone surrogates.
    """
    if isinstance(payload, bytes):
        if payload.startswith(_BOM):
            raise ValidationError("UTF-8 BOM is not allowed", path=path)
        if len(payload) > max_bytes:
            raise ValidationError(f"record exceeds {max_bytes} bytes", path=path)
        try:
            text = payload.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise ValidationError(f"invalid UTF-8: {exc}", path=path) from None
    else:
        text = payload
        if len(text.encode("utf-8")) > max_bytes:
            raise ValidationError(f"record exceeds {max_bytes} bytes", path=path)
        if text.startswith("\ufeff"):
            raise ValidationError("UTF-8 BOM is not allowed", path=path)
    if _has_lone_surrogate(text):
        # A lone surrogate can only arrive escaped; it is invalid Unicode text.
        raise ValidationError("lone surrogate in JSON text", path=path)
    try:
        value = json.loads(
            text,
            object_pairs_hook=_pairs_no_duplicates,
            parse_constant=_reject_constant,
        )
    except ValidationError as exc:
        raise ValidationError(exc.message, path=path) from None
    except json.JSONDecodeError as exc:
        raise ValidationError(f"malformed JSON: {exc.msg} at {exc.pos}", path=path) from None
    _assert_clean(value, path=path)
    return value


def _assert_clean(value: Any, *, path: str | None, _depth: int = 0) -> None:
    if _depth > 64:
        raise ValidationError("JSON nesting deeper than 64", path=path)
    if isinstance(value, str):
        if _has_lone_surrogate(value):
            raise ValidationError("lone surrogate in JSON string", path=path)
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValidationError("non-finite JSON number", path=path)
        return
    if isinstance(value, bool) or value is None or isinstance(value, int):
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValidationError("object keys must be strings", path=path)
            _assert_clean(item, path=path, _depth=_depth + 1)
        return
    if isinstance(value, list):
        for item in value:
            _assert_clean(item, path=path, _depth=_depth + 1)
        return
    raise ValidationError(f"unsupported JSON value type: {type(value).__name__}", path=path)


def _walk_numbers(value: Any, *, allow_unsafe: bool, path: str | None) -> None:
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return
    if isinstance(value, int):
        if not allow_unsafe and abs(value) > SAFE_INTEGER_MAX:
            raise ValidationError(
                f"integer {value} exceeds the safe identity range +/-{SAFE_INTEGER_MAX}; "
                "encode int64/uint64 counters as canonical integer strings",
                path=path,
            )
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValidationError("non-finite number cannot be canonicalized", path=path)
        # RFC 8785 / ECMAScript serializes both signs of IEEE-754 zero as "0".
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValidationError("object keys must be strings", path=path)
            _walk_numbers(item, allow_unsafe=allow_unsafe, path=path)
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _walk_numbers(item, allow_unsafe=allow_unsafe, path=path)
        return
    raise ValidationError(f"unsupported JSON value type: {type(value).__name__}", path=path)


def dumps(value: Any, *, allow_unsafe_integers: bool = False, path: str | None = None) -> bytes:
    """RFC 8785 canonical JSON bytes (UTF-8, sorted properties, ES number formatting)."""
    _assert_clean(value, path=path)
    _walk_numbers(value, allow_unsafe=allow_unsafe_integers, path=path)
    try:
        return rfc8785.dumps(value)
    except (rfc8785.CanonicalizationError, TypeError, ValueError) as exc:
        raise ValidationError(f"canonicalization failed: {exc}", path=path) from None


def text(value: Any) -> str:
    """Canonical JSON as text (no trailing newline)."""
    return dumps(value).decode("utf-8")


def jsonl_bytes(records: Iterable[Mapping[str, Any]], *, path: str | None = None) -> bytes:
    """Canonical JSONL: one canonical object plus LF per line (EVIDENCE_SPEC encoding)."""
    return b"".join(dumps(record, path=path) + b"\n" for record in records)


def parse_jsonl(payload: bytes, *, path: str | None = None) -> list[Any]:
    """Parse canonical JSONL strictly; blank lines are rejected, a missing final LF is not fatal."""
    if not payload:
        return []
    if payload.startswith(_BOM):
        raise ValidationError("UTF-8 BOM is not allowed", path=path)
    try:
        decoded = payload.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ValidationError(f"invalid UTF-8: {exc}", path=path) from None
    lines = decoded.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    out: list[Any] = []
    for number, line in enumerate(lines, start=1):
        if not line:
            raise ValidationError(f"blank JSONL line {number}", path=path)
        out.append(strict_loads(line, path=f"{path or '<jsonl>'}:{number}"))
    return out


def is_canonical(payload: bytes, *, path: str | None = None) -> bool:
    """True when stored bytes already equal their RFC 8785 form."""
    try:
        return dumps(strict_loads(payload, path=path), path=path) == payload
    except ValidationError:
        return False


def require_canonical(payload: bytes, *, path: str | None = None) -> Any:
    """Parse stored/signed bytes that must already be canonical (not human-edited)."""
    value = strict_loads(payload, path=path)
    if dumps(value, path=path) != payload:
        raise ValidationError("stored record is not in canonical RFC 8785 form", path=path)
    return value


def content_id(record: Mapping[str, Any], id_field: str, *, path: str | None = None) -> str:
    """Digest of the JCS preimage with the artifact's own ID field omitted.

    The record must carry ``schema_id`` and ``identity_algorithm == jcs-sha256-v1``; both remain
    inside the preimage so a schema or algorithm change yields a different identity.
    """
    if id_field not in record:
        raise ValidationError(f"record has no {id_field!r} field to omit", path=path)
    preimage = {key: value for key, value in record.items() if key != id_field}
    return digest_of(preimage, path=path)


def digest_of(value: Any, *, path: str | None = None) -> str:
    payload = dumps(value, path=path)
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def verify_content_id(record: Mapping[str, Any], id_field: str, *, path: str | None = None) -> None:
    if record.get("identity_algorithm") != JCS_IDENTITY_ALGORITHM:
        raise ValidationError(
            f"identity_algorithm must be {JCS_IDENTITY_ALGORITHM!r}", path=path
        )
    expected = content_id(record, id_field, path=path)
    if record.get(id_field) != expected:
        raise ValidationError(
            f"{id_field} does not match recomputed content id {expected}", path=path
        )


# --- value-level validators shared by schema checks and code-level invariants ----------------


def is_digest(value: Any) -> bool:
    return isinstance(value, str) and _DIGEST_RE.match(value) is not None


def is_uint_string(value: Any, *, maximum: int = _UINT64_MAX) -> bool:
    return isinstance(value, str) and _UINT_RE.match(value) is not None and int(value) <= maximum


def is_int_string(value: Any) -> bool:
    return (
        isinstance(value, str)
        and _INT_RE.match(value) is not None
        and _INT64_MIN <= int(value) <= _INT64_MAX
    )


def is_decimal_string(value: Any) -> bool:
    """Canonical decimal settings syntax: no exponent, no leading +, no trailing zeros, no -0."""
    if not isinstance(value, str) or _DECIMAL_RE.match(value) is None:
        return False
    if value.startswith("-0") and (len(value) == 2 or value[2] == "."):
        return False
    if "." in value and value.endswith("0"):
        return False
    return True


def expect_digest(value: Any, field: str, *, path: str | None = None) -> str:
    if not is_digest(value):
        raise ValidationError(f"{field} must be 'sha256:<64 lowercase hex>'", path=path)
    return value


# --- legacy research identity, preserved read-only -------------------------------------------


def legacy_canonical(value: Any) -> bytes:
    """The historical research serializer from ``audioml_eval.records.canonical``.

    ASCII-escaped, sorted keys. Kept only so old research hashes can be re-verified; it is *not*
    JCS and must never be used for new identities.
    """
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode("ascii")


def legacy_digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(legacy_canonical(value)).hexdigest()


def iter_duplicate_free_keys(value: Any) -> Iterator[str]:
    """Diagnostic helper used by tests to prove decoded-key collision handling."""
    if isinstance(value, Mapping):
        for key, item in value.items():
            yield key
            yield from iter_duplicate_free_keys(item)
    elif isinstance(value, list):
        for item in value:
            yield from iter_duplicate_free_keys(item)
