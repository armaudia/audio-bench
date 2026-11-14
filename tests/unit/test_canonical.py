# SPDX-FileCopyrightText: 2026 Tsakanyan Hovhannes
# SPDX-License-Identifier: Apache-2.0
import hashlib

import pytest

from audio_bench import canonical
from audio_bench.errors import ValidationError


def test_jcs_rfc8785_sample():
    value = {
        "numbers": [333333333.33333329, 1e30, 4.50, 2e-3, 1e-27],
        "string": "€$\x0f\nA'B\"\\\\\"/",
        "literals": [None, True, False],
    }
    expected = b'{"literals":[null,true,false],"numbers":[333333333.3333333,1e+30,4.5,0.002,1e-27],"string":"\xe2\x82\xac$\\u000f\\nA\'B\\\"\\\\\\\\\\\"/"}'
    assert canonical.dumps(value) == expected


def test_rfc_unicode_utf16_sort():
    value = {"\ue000": 1, "😀": 2, "a": 3}
    # UTF-16 sorts the emoji surrogate pair before U+E000.
    assert canonical.dumps(value).decode().startswith('{"a":3,"😀":2,"\ue000":1}')


@pytest.mark.parametrize("payload", [
    b'{"a":1,"a":2}',
    b'{"a":1,"\\u0061":2}',
    b'{"x":NaN}',
    b'{"x":Infinity}',
    b'\xef\xbb\xbf{}',
    b'{"x":"\\ud800"}',
    b'{"x":1} trailing',
    b'\xff',
])
def test_strict_rejects_ambiguous_or_invalid_json(payload):
    with pytest.raises(ValidationError):
        canonical.strict_loads(payload)


def test_large_transport_integer_is_a_string():
    value = {"monotonic_ns": "9007199254740993", "sample": "9223372036854775807"}
    payload = canonical.dumps(value)
    assert canonical.require_canonical(payload) == value
    with pytest.raises(ValidationError, match="safe identity range"):
        canonical.dumps({"counter": 9007199254740993})


def test_rfc8785_negative_zero_is_canonical_zero():
    assert canonical.dumps({"metric": -0.0}) == b'{"metric":0}'


@pytest.mark.parametrize(
    ("bits", "expected"),
    [
        ("0000000000000001", "5e-324"),
        ("8000000000000001", "-5e-324"),
        ("7fefffffffffffff", "1.7976931348623157e+308"),
        ("44b52d02c7e14af6", "1e+23"),
        ("444b1ae4d6e2ef50", "1e+21"),
        ("3eb0c6f7a0b5ed8d", "0.000001"),
    ],
)
def test_rfc8785_ecmascript_number_vectors(bits, expected):
    import struct

    number = struct.unpack(">d", bytes.fromhex(bits))[0]
    assert canonical.dumps({"n": number}) == ('{"n":' + expected + '}').encode()


def test_identity_omits_only_own_id():
    record = {"schema_id": "audio-bench/case-set/0.1", "identity_algorithm": "jcs-sha256-v1", "case_set_id": "", "x": 1}
    record["case_set_id"] = canonical.content_id(record, "case_set_id")
    canonical.verify_content_id(record, "case_set_id")
    record["x"] = 2
    with pytest.raises(ValidationError):
        canonical.verify_content_id(record, "case_set_id")


def test_legacy_identity_differs_from_jcs_on_unicode():
    value = {"e": "€"}
    assert canonical.legacy_canonical(value) == b'{"e":"\\u20ac"}'
    assert canonical.dumps(value) == b'{"e":"\xe2\x82\xac"}'
    assert canonical.legacy_digest(value) != canonical.digest_of(value)
