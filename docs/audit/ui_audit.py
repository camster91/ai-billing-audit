"""UI audit script for AI Pre-Bill Audit marketing site.

Captures full-page screenshots at desktop (1440px) and mobile (390px) for the
four public marketing routes, then runs the interactive checks called out in
the kanban task body (CTA above fold, pricing teaser visibility, mobile
horizontal scroll, tap-target sizing, dark-mode toggle / FOUC).

Outputs go to /tmp/portal-audit/screenshots/ and a JSON report at
/tmp/portal-audit/audit.json. The downstream writer ingests both.
"""

import json
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE = "http://localhost:3456"
OUT = Path("/tmp/portal-audit")
SHOTS = OUT / "screenshots"
SHOTS.mkdir(parents=True, exist_ok=True)

PAGES = [
    ("home", "/"),
    ("pricing", "/pricing"),
    ("how-it-works", "/how-it-works"),
    ("security", "/security"),
]
VIEWPORTS = {
    "desktop": {"width": 1440, "height": 900},
    "mobile": {"width": 390, "height": 844},
}

report = {"pages": {}, "interactive": {}, "errors": []}


def classify_tap_target(box):
    """Return 'ok' if >= 44px on both axes, else 'small' with dimensions."""
    w = box["width"]
    h = box["height"]
    if w >= 44 and h >= 44:
        return "ok", w, h
    return "small", w, h


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch()

        # 1. Full-page screenshots at both viewports for each public page
        for vname, vp in VIEWPORTS.items():
            ctx = browser.new_context(
                viewport=vp,
                device_scale_factor=2 if vname == "mobile" else 1,
                is_mobile=vname == "mobile",
                has_touch=vname == "mobile",
            )
            page = ctx.new_page()
            for label, path in PAGES:
                url = BASE + path
                try:
                    page.goto(url, wait_until="networkidle", timeout=30000)
                except Exception as e:
                    report["errors"].append(f"goto {url} ({vname}): {e}")
                    continue
                # Allow fonts/animations to settle
                page.wait_for_timeout(700)
                # Detect horizontal scrollbar
                scroll_w, client_w = page.evaluate(
                    "() => [document.documentElement.scrollWidth, document.documentElement.clientWidth]"
                )
                h_scroll = scroll_w > client_w + 1
                # Page size
                page_height = page.evaluate(
                    "() => document.documentElement.scrollHeight"
                )
                shot_path = SHOTS / f"{label}_{vname}.png"
                page.screenshot(path=str(shot_path), full_page=True)
                # Above-the-fold snapshot for CTA checks
                fold_path = SHOTS / f"{label}_{vname}_fold.png"
                page.screenshot(path=str(fold_path), full_page=False)
                # Discover primary CTAs (buttons + <a> with btn-like classes)
                cta_locators = page.evaluate(
                    """
                    () => {
                      const selectors = [
                        'a[class*="cta" i]', 'button[class*="cta" i]',
                        'a[class*="primary" i]', 'button[class*="primary" i]',
                        'a[href*="signup" i]', 'a[href*="register" i]',
                        'a[href*="checkout" i]', 'a[href*="/pricing" i]',
                        'a[href*="/portal" i]', 'a[href*="login" i]',
                      ];
                      const seen = new Set();
                      const out = [];
                      document.querySelectorAll(selectors.join(','))
                        .forEach((el) => {
                          if (seen.has(el)) return;
                          seen.add(el);
                          const r = el.getBoundingClientRect();
                          const text = (el.innerText || el.textContent || '').trim().slice(0, 80);
                          out.push({
                            tag: el.tagName,
                            text,
                            href: el.getAttribute('href') || '',
                            x: Math.round(r.x), y: Math.round(r.y),
                            w: Math.round(r.width), h: Math.round(r.height),
                            visible: r.width > 0 && r.height > 0,
                            aboveFold: r.top < window.innerHeight && r.bottom > 0,
                          });
                        });
                      return out;
                    }
                    """
                )
                # Tap-target audit on mobile only
                tap_targets = []
                if vname == "mobile":
                    tap_targets = page.evaluate(
                        """
                        () => {
                          const out = [];
                          document.querySelectorAll('a, button').forEach((el) => {
                            const r = el.getBoundingClientRect();
                            if (r.width === 0 || r.height === 0) return;
                            out.push({
                              tag: el.tagName,
                              text: (el.innerText || el.textContent || '').trim().slice(0, 60),
                              href: el.getAttribute('href') || '',
                              w: Math.round(r.width), h: Math.round(r.height),
                            });
                          });
                          return out;
                        }
                        """
                    )
                # Pricing teaser check on home only — look for any /pricing link in viewport
                pricing_link_above_fold = any(
                    c["aboveFold"]
                    and ("/pricing" in c["href"] or "pricing" in c["text"].lower())
                    for c in cta_locators
                )
                key = f"{label}_{vname}"
                report["pages"][key] = {
                    "url": url,
                    "viewport": vp,
                    "page_height_px": page_height,
                    "horizontal_scroll": h_scroll,
                    "scroll_w": scroll_w,
                    "client_w": client_w,
                    "full_screenshot": str(shot_path),
                    "fold_screenshot": str(fold_path),
                    "ctas": cta_locators,
                    "tap_targets": tap_targets if vname == "mobile" else None,
                    "pricing_link_above_fold": pricing_link_above_fold,
                }
            ctx.close()

        # 2. Dark-mode toggle / FOUC check on home
        ctx = browser.new_context(
            viewport=VIEWPORTS["desktop"],
            color_scheme="dark",
        )
        page = ctx.new_page()
        # Capture before any JS runs - look for FOUC
        try:
            page.goto(BASE + "/", wait_until="domcontentloaded", timeout=15000)
            initial_bg = page.evaluate(
                "() => getComputedStyle(document.body).backgroundColor"
            )
            initial_color = page.evaluate("() => getComputedStyle(document.body).color")
        except Exception as e:
            report["errors"].append(f"FOUC capture: {e}")
            initial_bg = initial_color = "?"
        page.wait_for_timeout(800)
        # Check for a theme toggle in the DOM
        toggle_info = page.evaluate(
            """
            () => {
              const candidates = Array.from(document.querySelectorAll(
                '[class*="theme" i], [class*="dark" i], [aria-label*="theme" i], [aria-label*="dark" i], button'
              ));
              const themes = [];
              candidates.forEach(el => {
                const r = el.getBoundingClientRect();
                if (r.width === 0) return;
                themes.push({
                  tag: el.tagName,
                  cls: el.className.toString().slice(0, 120),
                  label: el.getAttribute('aria-label') || '',
                  text: (el.innerText || '').trim().slice(0, 40),
                });
              });
              return {
                foundToggle: themes.length > 0,
                candidates: themes.slice(0, 10),
                htmlClass: document.documentElement.className,
                dataTheme: document.documentElement.getAttribute('data-theme'),
                colorSchemeMeta: document.querySelector('meta[name="color-scheme"]')?.content || null,
              };
            }
            """
        )
        page.screenshot(path=str(SHOTS / "home_dark_load.png"), full_page=False)
        # Reload + capture again at networkidle to compare
        page.reload(wait_until="networkidle")
        page.wait_for_timeout(500)
        reload_bg = page.evaluate(
            "() => getComputedStyle(document.body).backgroundColor"
        )
        page.screenshot(path=str(SHOTS / "home_dark_settled.png"), full_page=False)
        report["interactive"]["dark_mode"] = {
            "initial_bg": initial_bg,
            "initial_color": initial_color,
            "reload_bg": reload_bg,
            "found_toggle_in_dom": toggle_info["foundToggle"],
            "candidates": toggle_info["candidates"],
            "html_class": toggle_info["htmlClass"],
            "data_theme": toggle_info["dataTheme"],
            "color_scheme_meta": toggle_info["colorSchemeMeta"],
            "load_shot": str(SHOTS / "home_dark_load.png"),
            "settled_shot": str(SHOTS / "home_dark_settled.png"),
        }
        ctx.close()
        browser.close()

    # 3. Summarise tap-target findings
    small_tap = []
    for key, data in report["pages"].items():
        if not data.get("tap_targets"):
            continue
        for t in data["tap_targets"]:
            if t["w"] < 44 or t["h"] < 44:
                small_tap.append({"page": key, **t})
    report["interactive"]["small_tap_targets"] = small_tap[:80]

    out_json = OUT / "audit.json"
    out_json.write_text(json.dumps(report, indent=2))
    print(f"Wrote {out_json} ({out_json.stat().st_size} bytes)")
    print(f"Screenshots: {len(list(SHOTS.glob('*.png')))} files in {SHOTS}")
    print(f"Errors: {len(report['errors'])}")
    for e in report["errors"]:
        print(f"  - {e}")


if __name__ == "__main__":
    main()
