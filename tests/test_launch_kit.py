"""Contract tests for the approval-gated controlled-launch assets."""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse


ROOT = Path(__file__).resolve().parents[1]
KIT = ROOT / "docs" / "launch-kit"
MANIFEST = json.loads((KIT / "CLAIM_MANIFEST.json").read_text())


def test_every_asset_is_registered_draft_with_known_claims() -> None:
    claim_ids = {claim["id"] for claim in MANIFEST["claims"]}
    registered = {asset["path"] for asset in MANIFEST["assets"]}
    actual = {
        path.name
        for path in KIT.glob("*.md")
        if path.name not in {"README.md", "EXPORT_QA.md"}
    }

    assert registered == actual
    for claim in MANIFEST["claims"]:
        assert claim["source"]
        assert claim["approvalState"] == "review_required"
        assert claim["publicUse"] is False

    for asset in MANIFEST["assets"]:
        text = (KIT / asset["path"]).read_text()
        assert "> DRAFT -" in text
        assert set(re.findall(r"\bZC-\d{3}\b", text)) <= set(asset["claimIds"])
        assert set(asset["claimIds"]) <= claim_ids


def test_links_stay_on_approved_routes_with_non_personal_attribution() -> None:
    approved = {urlparse(url).path for url in MANIFEST["approvedPublicRoutes"]}
    url_pattern = re.compile(r"https://zorva\.ashbi\.ca[^\s)>]*")

    for asset in MANIFEST["assets"]:
        text = (KIT / asset["path"]).read_text()
        for raw_url in url_pattern.findall(text):
            parsed = urlparse(raw_url)
            assert parsed.path in approved
            query = parse_qs(parsed.query)
            assert set(query) <= {"utm_source", "utm_medium", "utm_campaign"}
            if query:
                assert query["utm_campaign"] == [MANIFEST["campaign"]]


def test_known_unsafe_claim_patterns_are_absent() -> None:
    patterns = [
        r"catches?\s+6[–-]7\s+of\s+10",
        r"data stays in a Canadian data centre",
        r"region[- ]pinned",
        r"HIPAA[- ]compliant",
        r"HIA[- ]compliant",
        r"\$\d+[,.]?\d*\s*(saved|recovered|per month)",
        r"\b\d+(?:\.\d+)?%\s+(accuracy|savings|reduction|improvement|ROI)",
    ]
    corpus = "\n".join(
        (KIT / asset["path"]).read_text() for asset in MANIFEST["assets"]
    )
    for pattern in patterns:
        assert not re.search(pattern, corpus, flags=re.IGNORECASE), pattern
