#!/usr/bin/env python3
"""
P11 bug-sweep batch fix: replace the leaky `console.error + raw e.message`
500 pattern with `internalErrorResponse()` from @/lib/api-errors.

Uses simple substring search rather than regex to avoid nested-brace
issues with the inner NextResponse.json({ ... }, { ... }) object.

Matches the exact 6-line shape:
    } catch (e) {
        const message = e instanceof Error ? e.message : "unknown";
        console.error("[<ROUTE>] error:", message);
        return NextResponse.json(
          { error: "internal_error", message },
          { status: 500 },
        );
      }

Idempotent: skips files already migrated (have internalErrorResponse).
"""

from __future__ import annotations
from pathlib import Path

ROOT = Path("/Users/biancabienaime/projects/ai-billing-audit/apps/portal/src/app/api")
TARGETS = [
    "billing/subscription/route.ts",
    "billing/invoices/route.ts",
    "billing/cancel-subscription/route.ts",
    "billing/change-tier/route.ts",
    "onboarding/upload/route.ts",
    "onboarding/ehr/route.ts",
    "onboarding/region/route.ts",
    "onboarding/state/route.ts",
    "onboarding/redeem/route.ts",
    "onboarding/clinic-profile/route.ts",
    "onboarding/complete/route.ts",
    "onboarding/first-encounter/route.ts",
    "settings/phi-redaction/route.ts",
    "settings/clinic-profile/route.ts",
]


def fix_one(rel: str) -> tuple[bool, str]:
    p = ROOT / rel
    src = p.read_text(encoding="utf-8")
    if "internalErrorResponse" in src:
        return (False, "already migrated")
    # Split into lines for line-based replacement (preserves indentation).
    lines = src.split("\n")
    # Find the catch block by anchor: 'const message = e instanceof Error'
    catch_start = -1
    for i, ln in enumerate(lines):
        if "const message = e instanceof Error" in ln:
            catch_start = i - 1  # the line above is '} catch (e) {'
            break
    if catch_start < 0:
        return (False, "no catch anchor")
    # Find the close brace: walk forward to find the line containing only "  }"
    # at the indentation of the catch line.
    catch_indent_len = len(lines[catch_start]) - len(lines[catch_start].lstrip())
    expected_close_indent = (
        " " * (catch_indent_len - 2) + "}"
    )  # two spaces less than catch
    catch_end = -1
    for i in range(catch_start + 6, min(catch_start + 20, len(lines))):
        if lines[i].strip() == "}" and lines[i].startswith(
            expected_close_indent[: len(lines[i]) - len(lines[i].lstrip())]
        ):
            catch_end = i
            break
    if catch_end < 0:
        return (False, "no close brace found")
    # Extract the route from the console.error line.
    # Format: console.error("[<ROUTE>] error:", message);
    console_line = lines[catch_start + 2]
    if "] error:" not in console_line:
        return (False, f"unexpected console.error line: {console_line!r}")
    route_in_log = console_line.split("] error:")[0].rsplit('"', 1)[-1]
    # Build the replacement: preserve the leading indentation of the catch line.
    indent = lines[catch_start][
        : len(lines[catch_start]) - len(lines[catch_start].lstrip())
    ]
    new_block_lines = [
        f"{indent}}} catch (e) {{",
        f'{indent}  return internalErrorResponse(request, e, "{route_in_log}");',
        f"{indent}}}",
    ]
    new_lines = lines[:catch_start] + new_block_lines + lines[catch_end + 1 :]
    new_src = "\n".join(new_lines)
    # Make sure the import is added (idempotent: only if missing).
    import_line = 'import { internalErrorResponse } from "@/lib/api-errors";'
    if 'from "@/lib/api-errors"' not in new_src:
        new_lines = new_src.split("\n")
        last_lib_import = -1
        for i, ln in enumerate(new_lines):
            if ln.startswith("import ") and '"@/lib/' in ln:
                last_lib_import = i
        if last_lib_import >= 0:
            new_lines.insert(last_lib_import + 1, import_line)
        else:
            # Fallback: insert after the first import.
            for i, ln in enumerate(new_lines):
                if ln.startswith("import "):
                    new_lines.insert(i + 1, import_line)
                    break
        new_src = "\n".join(new_lines)
    p.write_text(new_src, encoding="utf-8")
    return (True, f"fixed (route={route_in_log})")


if __name__ == "__main__":
    fixed = 0
    for rel in TARGETS:
        ok, msg = fix_one(rel)
        flag = "OK " if ok else ".. "
        print(f"{flag} {rel}  -> {msg}")
        if ok:
            fixed += 1
    print(f"\n{fixed}/{len(TARGETS)} files migrated.")
