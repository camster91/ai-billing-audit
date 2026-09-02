#!/usr/bin/env python3
"""Build or verify the deterministic Zorva candidate-asset manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs" / "BRAND_ASSET_MANIFEST.json"


def selected_files() -> list[Path]:
    roots = (
        ROOT / "assets" / "brand" / "source",
        ROOT / "apps" / "portal" / "public" / "brand",
        ROOT / "apps" / "portal" / "public" / "app-icons",
    )
    files = [path for root in roots for path in root.rglob("*") if path.is_file()]
    files.extend(
        ROOT / path
        for path in (
            "apps/portal/public/favicon.ico",
            "apps/portal/public/favicon-16x16.png",
            "apps/portal/public/favicon-32x32.png",
            "apps/portal/public/favicon-48x48.png",
            "apps/portal/public/icon.svg",
            "apps/portal/public/icon-dark.svg",
            "apps/mobile/www/zorva-mark.svg",
            "src/ai_billing_audit/static/favicon.ico",
            "src/ai_billing_audit/static/favicon-32.png",
            "src/ai_billing_audit/static/favicon.svg",
            "src/ai_billing_audit/static/apple-touch-icon.png",
        )
    )
    return sorted(files, key=lambda path: path.relative_to(ROOT).as_posix())


def build_manifest() -> dict[str, object]:
    assets = []
    for path in selected_files():
        payload = path.read_bytes()
        assets.append(
            {
                "path": path.relative_to(ROOT).as_posix(),
                "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
    return {
        "schemaVersion": 1,
        "status": "candidate_pending_human_brand_approval",
        "brandOwner": "Cameron Ashley",
        "constructionSource": "assets/brand/source",
        "generator": "scripts/build-brand-assets.sh",
        "creatorRecord": (
            "Original geometric construction produced within this repository; "
            "no stock artwork or third-party logo asset was used."
        ),
        "rightsBasis": (
            "Candidate project artwork. Inter is referenced but not embedded in "
            "wordmark SVGs. Final ownership acceptance and trademark clearance "
            "have not been completed."
        ),
        "approvalGates": {
            "humanBrandApproval": False,
            "trademarkClearance": False,
            "productionPublication": False,
        },
        "accessibility": {
            "standaloneMark": "Use the accessible name Zorva.",
            "adjacentToBrandText": "Treat as decorative with empty alt text.",
            "faviconsAndAppIcons": "The surrounding browser or operating system supplies the app name.",
        },
        "consumers": [
            "Next.js metadata and web manifest",
            "Next.js public header",
            "FastAPI browser and structured-data metadata",
            "Capacitor mobile fallback splash",
        ],
        "assets": assets,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    rendered = json.dumps(build_manifest(), indent=2, ensure_ascii=False) + "\n"
    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_text() != rendered:
            raise SystemExit("brand asset manifest is stale; rebuild it")
        print(f"Brand asset manifest verified: {len(build_manifest()['assets'])} files")
        return 0
    OUTPUT.write_text(rendered)
    print(f"Brand asset manifest written: {len(build_manifest()['assets'])} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
