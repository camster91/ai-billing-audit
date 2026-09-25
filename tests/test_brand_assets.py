"""Contract tests for the candidate Zorva brand asset pack."""

from __future__ import annotations

import json
import struct
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PORTAL_PUBLIC = ROOT / "apps" / "portal" / "public"


def png_size(path: Path) -> tuple[int, int]:
    payload = path.read_bytes()
    assert payload[:8] == b"\x89PNG\r\n\x1a\n"
    return struct.unpack(">II", payload[16:24])


def test_manifest_is_current_and_assets_exist() -> None:
    subprocess.run(
        ["python3", "scripts/build-brand-asset-manifest.py", "--check"],
        cwd=ROOT,
        check=True,
    )
    manifest = json.loads((ROOT / "docs" / "BRAND_ASSET_MANIFEST.json").read_text())
    assert manifest["status"] == "candidate_pending_human_brand_approval"
    assert manifest["approvalGates"] == {
        "humanBrandApproval": False,
        "trademarkClearance": False,
        "productionPublication": False,
    }
    assert len(manifest["assets"]) == 47
    assert all((ROOT / asset["path"]).is_file() for asset in manifest["assets"])


def test_svg_sources_are_safe_and_use_the_candidate_palette() -> None:
    allowed = {"#0D9488", "#14B8A6", "#1E293B", "#F8FAFC", "#FFF"}
    for path in (ROOT / "assets" / "brand" / "source").glob("*.svg"):
        root = ET.fromstring(path.read_text())
        assert root.attrib["viewBox"]
        assert not list(root.iter("script"))
        content = path.read_text()
        assert "http://" not in content.replace("http://www.w3.org/2000/svg", "")
        colors = {token for token in allowed if token in content}
        assert colors
        assert "gradient" not in content.lower()


def test_favicon_and_app_icon_dimensions() -> None:
    for size in (16, 32, 48):
        assert png_size(PORTAL_PUBLIC / f"favicon-{size}x{size}.png") == (size, size)
    for size in (192, 512):
        assert png_size(PORTAL_PUBLIC / "app-icons" / f"android-{size}.png") == (
            size,
            size,
        )
    for size in (1024, 180, 167, 152, 120, 87, 80, 60, 58, 40, 29):
        assert png_size(PORTAL_PUBLIC / "app-icons" / f"ios-{size}.png") == (size, size)
    for size in (16, 32, 64, 128, 256, 512, 1024):
        assert png_size(PORTAL_PUBLIC / "app-icons" / f"macos-{size}.png") == (
            size,
            size,
        )


def test_consumers_reference_existing_assets_and_safe_alt_treatment() -> None:
    metadata = (
        ROOT / "apps" / "portal" / "src" / "lib" / "public-marketing-metadata.ts"
    ).read_text()
    layout = (ROOT / "apps" / "portal" / "src" / "app" / "layout.tsx").read_text()
    mobile = (ROOT / "apps" / "mobile" / "www" / "index.html").read_text()
    assert 'manifest: "/manifest.webmanifest"' in metadata
    assert "/brand/zorva-mark-dark.svg" in layout
    assert 'alt=""' in layout and 'aria-hidden="true"' in layout
    assert 'src="zorva-mark.svg" alt="Zorva"' in mobile
    assert "https://zorva.ashbi.ca/" in mobile
    assert (
        "#2563eb"
        not in (
            ROOT / "src" / "ai_billing_audit" / "static" / "favicon.svg"
        ).read_text()
    )
