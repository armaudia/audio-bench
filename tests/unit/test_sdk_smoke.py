import os
from pathlib import Path

import pytest

from audio_bench.bundle import validate_bundle
from audio_bench.report import build_report
from audio_bench.smoke import run_sdk_smoke


ROOT = Path(__file__).resolve().parents[2]
SDK_PREFIX = Path(os.environ.get("AUDIO_SDK_PREFIX", ROOT.parent / "audio-sdk/build/candidate/audio-sdk-0.1.0"))
NATIVE_BUILD = Path(os.environ.get("AUDIO_BENCH_NATIVE_BUILD", ROOT / "build/native"))


@pytest.mark.sdk
@pytest.mark.skipif(
    not (SDK_PREFIX / "bin/audio_sdk_conformance").is_file()
    or not (NATIVE_BUILD / "audio_bench_collect").is_file(),
    reason="verified installed SDK/native build is not available",
)
def test_installed_sdk_smoke_seals_valid_bundle_and_report(tmp_path):
    bundle = tmp_path / "bundle"
    result = run_sdk_smoke(
        bundle,
        native_build=NATIVE_BUILD,
        sdk_prefix=SDK_PREFIX,
        repository=ROOT,
    )
    assert result["cases"] == 24
    assert result["metrics_per_case"] == 7
    checked = validate_bundle(bundle)
    assert checked.valid, checked.errors
    report = build_report(bundle, tmp_path / "report")
    assert report["rows"] == 1
    assert report["media_bytes"] == 0
    assert "not_assessed" in (tmp_path / "report/index.html").read_text()
