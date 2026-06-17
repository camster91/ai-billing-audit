"""Smoke-test the demo dashboard in-process.

Uses ``starlette.testclient.TestClient`` (httpx-backed) to hit every
registered route and assert the response shape. The visual QA pass
(kanban t_e88a2734) runs the same script after every encounter is
wired, then opens the live URL in a real browser to check the visual
contract.

Run with::

    python scripts/smoke_dashboard.py

Exit code 0 on success, non-zero on the first failed assertion.
"""
from __future__ import annotations

import sys
from typing import Iterable

from starlette.testclient import TestClient

from ai_billing_audit.api import app
from ai_billing_audit.demo_registry import list_demo_encounters


def main(argv: Iterable[str] | None = None) -> int:
    del argv  # no flags for now
    client = TestClient(app)
    failures: list[str] = []

    # 1. /healthz
    r = client.get("/healthz")
    if r.status_code != 200:
        failures.append(f"/healthz expected 200 got {r.status_code}")
    else:
        body = r.json()
        n = body.get("n_registered", 0)
        if n < 1:
            failures.append(f"/healthz reports n_registered={n}, expected >= 1")
        else:
            print(f"  /healthz ok, n_registered={n}")

    # 2. / (index)
    r = client.get("/")
    if r.status_code != 200:
        failures.append(f"/ expected 200 got {r.status_code}")
    else:
        html = r.text
        registered = list_demo_encounters()
        for entry in registered:
            if entry.encounter_id not in html:
                failures.append(
                    f"/ index is missing card for {entry.encounter_id}"
                )
        if 'class="encounter-card' not in html:
            failures.append("/ index has no .encounter-card element")
        else:
            print(f"  / ok, lists {len(registered)} card(s)")

    # 3. /encounter/<id> for every registered encounter
    for entry in list_demo_encounters():
        r = client.get(f"/encounter/{entry.encounter_id}")
        if r.status_code != 200:
            failures.append(
                f"/encounter/{entry.encounter_id} expected 200 got {r.status_code}"
            )
            continue
        html = r.text
        # The evidence-highlight contract: at least one <mark class="evidence">
        # span must be present on the detail page if the encounter has a
        # gold finding with a non-empty quote.
        if 'class="evidence"' not in html and 'class="evidence evidence-off' not in html:
            failures.append(
                f"/encounter/{entry.encounter_id} has no <mark class='evidence'>"
                " element — evidence highlight is not visible"
            )
        # Clickable buttons: every button rendered must be a real <button>,
        # not a <button disabled> or a <button>...</button> with no
        # handler. We assert that the JS-attached data-action attrs and
        # the #btn-toggle-mark id are present.
        if "data-action=\"copy-quote\"" not in html:
            failures.append(
                f"/encounter/{entry.encounter_id} is missing copy-quote buttons"
            )
        if "data-action=\"scroll-to-note\"" not in html:
            failures.append(
                f"/encounter/{entry.encounter_id} is missing scroll-to-note buttons"
            )
        if 'id="btn-toggle-mark"' not in html:
            failures.append(
                f"/encounter/{entry.encounter_id} is missing the toggle-mark button"
            )
        if "<button" not in html:
            failures.append(
                f"/encounter/{entry.encounter_id} has no <button> at all"
            )
        # Difficulty badge
        if entry.difficulty not in html:
            failures.append(
                f"/encounter/{entry.encounter_id} missing difficulty badge "
                f"{entry.difficulty!r}"
            )
        print(f"  /encounter/{entry.encounter_id} ok")

    # 4. /encounter/<id>/json for every registered encounter
    for entry in list_demo_encounters():
        r = client.get(f"/encounter/{entry.encounter_id}/json")
        if r.status_code != 200:
            failures.append(
                f"/encounter/{entry.encounter_id}/json expected 200 got {r.status_code}"
            )
            continue
        body = r.json()
        if body.get("encounter_id") != entry.encounter_id:
            failures.append(
                f"/encounter/{entry.encounter_id}/json returned "
                f"encounter_id={body.get('encounter_id')!r}"
            )
        print(f"  /encounter/{entry.encounter_id}/json ok")

    # 5. /encounter/<bogus> → 404
    r = client.get("/encounter/does-not-exist")
    if r.status_code != 404:
        failures.append(f"/encounter/does-not-exist expected 404 got {r.status_code}")
    else:
        print("  /encounter/does-not-exist -> 404 ok")

    if failures:
        print("\nFAILURES:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("\nAll dashboard smoke checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
