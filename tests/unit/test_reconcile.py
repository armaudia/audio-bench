import json

import pytest

from audio_bench.errors import ImmutableViolation
from audio_bench.reconcile import impact_plan, reconcile_latest


def test_impact_plan_is_conservative_and_deterministic():
    assert impact_plan(["report/assets/app.js"])["tier"] == "rebuild_reports"
    assert impact_plan(["native/src/driver.cpp"])["tier"] == "reexecute_affected_configurations_and_revalidate"
    assert impact_plan(["unknown/custom.py"])["tier"] == "full_revalidation_and_reexecution"


def test_reconciliation_is_idempotent_serialized_and_protects_latest(tmp_path):
    first = "sha256:" + "1" * 64
    second = "sha256:" + "2" * 64
    assert reconcile_latest(tmp_path, source_branch="main", scope="quality", sequence=1,
                            request_id="req-1", core_digest=first, complete=False)["advanced"] is False
    assert reconcile_latest(tmp_path, source_branch="main", scope="quality", sequence=1,
                            request_id="req-1", core_digest=first, complete=True)["advanced"] is True
    latest_path = tmp_path / "latest/main/quality.json"
    latest_before = latest_path.read_bytes()
    assert reconcile_latest(tmp_path, source_branch="main", scope="quality", sequence=1,
                            request_id="req-1", core_digest=first, complete=True)["reason"] == "idempotent"
    assert reconcile_latest(tmp_path, source_branch="main", scope="quality", sequence=2,
                            request_id="req-2", core_digest=None, complete=False)["advanced"] is False
    assert reconcile_latest(tmp_path, source_branch="main", scope="quality", sequence=3,
                            request_id="req-3", core_digest=second, complete=True)["advanced"] is True
    assert reconcile_latest(tmp_path, source_branch="main", scope="quality", sequence=2,
                            request_id="late-req", core_digest=first, complete=True)["reason"] == "out_of_order"
    assert json.loads(latest_path.read_text())["sequence"] == "3"
    assert latest_path.read_bytes() != latest_before
    with pytest.raises(ImmutableViolation):
        reconcile_latest(tmp_path, source_branch="main", scope="quality", sequence=3,
                         request_id="req-3", core_digest=first, complete=True)
