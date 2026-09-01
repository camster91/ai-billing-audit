"""Regression checks for the portal's release-runtime contract."""

from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PORTAL = ROOT / "apps" / "portal"
EXPECTED_NODE = "22.23.2"
EXPECTED_ENGINE = ">=22.23 <23"
EXPECTED_PNPM = "pnpm@9.15.9"


def test_package_and_container_use_one_supported_node_line() -> None:
    package = json.loads((PORTAL / "package.json").read_text())
    dockerfile = (PORTAL / "Dockerfile").read_text()

    assert package["engines"]["node"] == EXPECTED_ENGINE
    assert package["packageManager"] == EXPECTED_PNPM

    image = re.search(
        r"^ARG NODE_IMAGE=node:([^@]+)@sha256:([0-9a-f]{64})$",
        dockerfile,
        re.MULTILINE,
    )
    assert image, "Dockerfile must pin the official Node image and digest"
    assert image.group(1) == f"{EXPECTED_NODE}-slim"
    assert dockerfile.count("FROM ${NODE_IMAGE}") == 3


def test_github_browser_and_build_gates_use_production_node() -> None:
    for workflow in ("e2e.yml", "test-on-pr.yml"):
        content = (ROOT / ".github" / "workflows" / workflow).read_text()
        versions = re.findall(r'node-version:\s*["\']([^"\']+)["\']', content)
        assert versions == [EXPECTED_NODE], (workflow, versions)


def test_operator_docs_do_not_direct_engineering_to_eol_node_20() -> None:
    current_sources = (
        ROOT / "CONTRIBUTING.md",
        ROOT / "README.md",
        ROOT / "docs" / "MASTER_PLAN.md",
        ROOT / "docs" / "MARKETING_PUBLIC_LAUNCH_GATES.md",
    )
    stale_instruction = re.compile(r"(?:pinned |under |runtime:\s*)Node 20", re.I)
    for source in current_sources:
        assert not stale_instruction.search(source.read_text()), source
