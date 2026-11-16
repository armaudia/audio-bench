# SPDX-FileCopyrightText: 2026 Tsakanyan Hovhannes
# SPDX-License-Identifier: Apache-2.0

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from check_corpus_rights import check_corpus_rights  # noqa: E402


@pytest.mark.parametrize("dataset", ["voices", "voicebank-demand", "dns5"])
def test_current_corpus_rights_allow_evaluation_but_deny_public_cache(dataset):
    assert check_corpus_rights(dataset, "evaluation", root=ROOT)["operation"] == "evaluation"
    with pytest.raises(ValueError, match="not cleared for redistribution"):
        check_corpus_rights(dataset, "public-cache", root=ROOT)


def test_public_cache_requires_redistribution_evidence_attribution_and_license_sources(tmp_path):
    manifest = {
        "status": "allowed",
        "rights": {"evaluation": "allowed", "redistribution": "allowed"},
        "public_actions_cache": "allowed",
        "public_cache_evidence_ref": "https://example.test/permission",
        "cache_attribution": "Dataset owner; citation and license link",
        "cache_license_sources": [{
            "title": "Dataset record", "license": "CC BY 4.0", "url": "https://example.test/license"
        }],
    }
    status_path = tmp_path / "manifests/voicebank.status.json"
    status_path.parent.mkdir(parents=True)
    status_path.write_text(json.dumps(manifest))

    notice = check_corpus_rights("voicebank-demand", "public-cache", root=tmp_path,
                                 cache_root=tmp_path / "cache")
    notice_path = tmp_path / "cache/voicebank-demand-test-v1/RIGHTS_NOTICE.json"
    assert json.loads(notice_path.read_text()) == notice
    assert notice["licenses"][0]["license"] == "CC BY 4.0"


def test_public_cache_rejects_missing_component_license_reference(tmp_path):
    manifest = {
        "status": "allowed",
        "rights": {"evaluation": "allowed", "redistribution": "allowed"},
        "public_actions_cache": "allowed",
        "public_cache_evidence_ref": "https://example.test/permission",
        "cache_attribution": "Dataset owner",
        "cache_license_sources": [{"title": "", "license": "CC BY 4.0", "url": "https://example.test/license"}],
    }
    status_path = tmp_path / "manifests/dns5.status.json"
    status_path.parent.mkdir(parents=True)
    status_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="must list every source license"):
        check_corpus_rights("dns5", "public-cache", root=tmp_path)
