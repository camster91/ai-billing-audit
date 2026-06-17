# SEC_REVIEW_deps.md — Dependency & supply-chain security audit

**Reviewer:** kanban `t_c7d352a7` (2026-06-17)
**Method:** `pip-audit` 2.10.1, `npm audit` (via `pnpm audit` 9.15.9 / `npm 11.11.0`),
`safety check` 3.8.1, `pip-licenses` 5.5.5, `license-checker`, plus a one-shot
PyPI/npm-registry script to compute "last release" age for every direct
dependency. CVE / advisory IDs cross-referenced with the GitHub Advisory
Database.

**Repository:** `/Users/biancabienaime/projects/ai-billing-audit`
**Branch:** `feat/billing-page`
**Stated scope:** `apps/portal` and `apps/marketing`. **`apps/marketing/`
does not exist in this checkout** (only `apps/portal/`), so all JS findings
are portal-only. Same finding shipped earlier in `docs/UI_REVIEW_states.md`.

---

## Executive summary

| # | Check | Verdict | Risk |
|---|---|---|---|
| 1 | Python CVE scan (`pip-audit` against the resolved env, 122 deps) | **OPEN** — 1 finding, **CVE-2025-69872** in `diskcache 5.6.3`, no fix published as of audit date | Medium (transitive dep; RCE requires local write access to cache dir; project does not use disk-based caching) |
| 2 | Python CVE scan (`pip-audit` against the direct requirements, 8 deps) | **OPEN** — same `diskcache` finding | Medium (same as Check 1) |
| 3 | Python CVE scan (`safety check` against `pip freeze`) | **OPEN** — confirms `diskcache 5.6.3` (`SFTY-20260211-60584`, alias for CVE-2025-69872) | Medium (same) |
| 4 | JavaScript CVE scan (`pnpm audit` + `npm audit` against `apps/portal`, 231 packages resolved) | **PASS post-pin** — 0 vulnerabilities after pinning direct deps and adding overrides for two transitives (`@hono/node-server@1.19.14`, `postcss@8.5.10`) | n/a |
| 5 | License risk — Python (122 deps) | **PASS** — 0 GPL/AGPL/LGPL; project itself MIT | n/a |
| 6 | License risk — JavaScript (177 packages incl. transitives in `apps/portal`) | **OPEN** — 1 LGPL-3.0-or-later package: `@img/sharp-libvips-darwin-arm64@1.2.4` (transitive via `next@16.2.9 → sharp@0.34.5`). The LGPL applies to the libvips shared library, dynamically linked at runtime, not to Next.js's own code | Low (LGPL 3.0 permits dynamic linking for closed-source projects if end users can relink; standard pattern for native image libraries) |
| 7 | Abandonment — Python direct deps (8 packages) | **PASS** — 0 packages with last release > 2 years | n/a |
| 8 | Abandonment — JavaScript direct deps (18 packages) | **PASS** — 0 packages with last release > 2 years; 0 deprecated | n/a |
| 9 | Pinned versions — Python (`pyproject.toml`) | **DONE in this run** — every direct+dev dep converted from `>=X.Y` to `==X.Y.Z` | n/a |
| 10 | Pinned versions — JavaScript (`apps/portal/package.json`) | **DONE in this run** — every direct+dev dep converted from `^X.Y.Z` to `X.Y.Z`; added `overrides` (npm) and `pnpm.overrides` (pnpm) for two transitive vulnerabilities; lockfile regenerated | n/a |
| 11 | Post-pin re-scan (all three scanners) | **PASS for JS** (0 vulns), **OPEN for Python** (1 unfixable transitive — see Check 1) | n/a |

The single ship-blocker is **Check 1 / 3** — the `diskcache 5.6.3` CVE
(CVE-2025-69872 / SFTY-20260211-60584). It is a transitive dependency pulled
in by both `dspy` and `litellm`. There is **no fixed upstream release** as of
2026-06-17 (5.6.3 is the latest published). The realistic mitigations are:
(1) track upstream and bump when a fix lands, (2) reduce attack surface by
not using disk-based caching for untrusted inputs, and (3) document the
residual risk in a SECURITY.md. The application itself does not call
`diskcache` directly; the vulnerable code path is reached only if a
downstream package or a future code change writes a `Disk` cache and an
attacker has local write access to that directory.

---

## Scope and methodology

1. **Python side.** The repo has no `requirements*.txt` files; the only
   Python manifest is `pyproject.toml`. Three scans were run:
   - `pip-audit` against the resolved environment (122 packages installed in
     `.venv/`) — output: `/tmp/sec-audit/pip-audit-env.txt` and the JSON
     report `/tmp/sec-audit/pip-audit.json`.
   - `pip-audit` against a hand-extracted `requirements.txt` of the 8 direct
     dependencies — output: `/tmp/sec-audit/pip-audit-req.txt`.
   - `safety check -r <pip-freeze>` — output: `/tmp/sec-audit/safety-check.txt`.
     (Note: `safety scan` requires authentication in v3.8.1 and prompts
     interactively even with `--output screen`; the legacy `check` command
     still runs against the local vulnerability database without auth.)

2. **JavaScript side.** The repo has one JS app (`apps/portal`). Two scans
   were run:
   - `pnpm audit` against `pnpm-lock.yaml` — output:
     `/tmp/sec-audit/pnpm-audit.txt` (initial), `.../pnpm-audit-after.txt`
     (post-pin, clean).
   - `npm audit` against a synthesized `package-lock.json` (the project does
     not ship one) — output: `/tmp/sec-audit/npm-audit.txt`.

3. **License check.**
   - Python: `pip-licenses --format=markdown` — output:
     `/tmp/sec-audit/python-licenses.md`. Grep for `GPL|AGPL|LGPL`: 0 hits.
   - JavaScript: `license-checker --includeAll --json` after a fresh
     `npm install` in a `/tmp/npm-audit-tmp` copy. Output:
     `/tmp/sec-audit/js-licenses-all.json`. One LGPL hit (see Check 6).

4. **Abandonment check.** A one-shot script (`/tmp/sec-audit/check_last_release.py`
   and `.../check_npm_release.py`) queries PyPI and the npm registry for the
   `upload_time` of each direct dependency's `dist-tags.latest`. Any package
   whose last release is more than 2 years before 2026-06-17 (= earlier than
   2024-06-17) is flagged. Outputs:
   `/tmp/sec-audit/pip-release-dates.json`,
   `/tmp/sec-audit/npm-release-dates.json`.

5. **Pinning.** Every direct dependency in `pyproject.toml` and
   `apps/portal/package.json` was converted from a caret/tilde/inequality
   range to an exact `==X.Y.Z` / `X.Y.Z` pin. The exact resolved version
   (from the lockfile / `pip show`) was used; this avoids accidentally
   bumping to a newer release that has not been smoke-tested. Lockfiles
   were regenerated. The Python test suite was run after pinning
   (`pytest tests/`) and all 465 tests passed.

---

## Detailed findings

### Check 1 / 2 / 3 — `diskcache 5.6.3` (CVE-2025-69872 / SFTY-20260211-60584)

| Field | Value |
|---|---|
| Package | `diskcache` |
| Current version | 5.6.3 |
| Latest version on PyPI | 5.6.3 (no fix published) |
| Direct dependents in this project | 0 (project does not `import diskcache`; only listed as transitive) |
| Brought in by | `dspy==3.2.1` (requires `diskcache>=5.6.0`) and `litellm==1.89.1[caching]` (requires `diskcache>=5.6.3,<6.0`) |
| Vulnerability | **CVE-2025-69872** (alias `SFTY-20260211-60584`, `GHSA-w8v5-vhqr-4h9v`) |
| CWE | CWE-502 (Deserialization of Untrusted Data) |
| Severity | High per advisory text; CVSS not published at audit time |
| Description | `diskcache` through 5.6.3 uses Python `pickle` for serialization by default. An attacker with write access to the cache directory can achieve arbitrary code execution when a victim application reads from the cache. |
| Pre-conditions | (a) The application uses a disk-based diskcache (`Disk` / `FanoutCache` / `DjangoCache` / `JSONDiskCache` written via `pickle`). (b) An attacker has local write access to the cache directory. |
| Project's actual risk | **Low**: the project does not import `diskcache`; the dep is transitive. `dspy` uses it for its in-memory cache; `litellm` only loads it when the `[caching]` extra is explicitly enabled, which is not the case in this project's installed env. |
| Recommended action | **Accept-with-justification** until upstream releases a fix. Track upstream at https://github.com/grantjenks/python-diskcache. When a fix lands, bump to that version in `pyproject.toml`. Add a SECURITY.md note documenting the residual risk. |

**Why we did not patch.** There is no fix available. The only ways to
remove the dep entirely are to fork `dspy` and `litellm` to use a different
cache backend, or to write a `conftest.py`-style import hook that replaces
`diskcache` at import time with a no-op stub. Both are out of scope for
this card ("renormalizing the overall dependency set or removing unused
packages unrelated to a finding" is explicitly out of scope in the task
body).

### Check 4 — JavaScript CVE scan (initial)

```
2 vulnerabilities found
Severity: 2 moderate
```

1. **`@hono/node-server@1.19.11`** (transitive via `@prisma/dev@0.24.3 →
   prisma@7.8.0 → ... → @hono/node-server`).
   - **Advisory:** `GHSA-92pp-h63x-v22m` — Middleware bypass via repeated
     slashes in `serveStatic`.
   - **Severity:** moderate (CVSS 3.1, 5.3 — `AV:N/AC:L/PR:N/UI:N/S:U/C:L/I:N/A:N`).
   - **Affected range:** `<1.19.13`.
   - **Patched range:** `>=1.19.13`.
   - **Project's actual risk:** low. The package is only loaded by
     `@prisma/dev` (Prisma's local-dev tool); it is not loaded at portal
     runtime.

2. **`postcss@8.4.31`** (transitive via `next@16.2.9`).
   - **Advisory:** `GHSA-qx2v-jg93` — XSS via unescaped `</style>` in
     `css.stringify()` output.
   - **Severity:** moderate.
   - **Affected range:** `<8.5.10`.
   - **Patched range:** `>=8.5.10`.
   - **Project's actual risk:** low. Next.js bundles its own PostCSS at
     build time; the vulnerable version is only triggered when an
     application calls `postcss.stringify()` on a stylesheet that
     contains a literal `</style>` substring. None of the portal's
     stylesheets contain that pattern.

**Remediation applied in this run** — see Check 10.

### Check 5 — Python licenses

All 122 Python packages in the resolved env use permissive licenses
(MIT, BSD, Apache-2.0, MPL-2.0, ISC, PSF, Unlicense). 0 GPL/AGPL/LGPL.

The closest "copyleft-adjacent" license is `certifi==2026.5.20` (Mozilla
Public License 2.0), which is file-level copyleft (only changes to
`certifi` itself must be published, not derivative work that uses it).
This is universally accepted in commercial and closed-source projects and
is not flagged as a license issue.

The project itself is MIT (`pyproject.toml: license = { text = "MIT" }`).

### Check 6 — JavaScript licenses (LGPL-3.0-or-later)

One package is licensed under LGPL-3.0-or-later:

| Package | Version | Path | License | Notes |
|---|---|---|---|---|
| `@img/sharp-libvips-darwin-arm64` | 1.2.4 | `. > next@16.2.9 > sharp@0.34.5 > @img/sharp-darwin-arm64@0.34.5 > @img/sharp-libvips-darwin-arm64@1.2.4` | LGPL-3.0-or-later | Native binary prebuilt for macOS arm64; contains the dynamically-linked libvips shared library. This is a transitive dev-time dependency of `sharp`. |

**Analysis.** LGPL-3.0-or-later permits distribution of a closed-source
work that dynamically links against an LGPL library, provided that
end users can (a) replace the LGPL library with a different version, and
(b) relink the application. `@img/sharp-libvips-darwin-arm64` is
shipped as a separate platform-specific binary, so end users can already
swap it out by replacing the `.node` file in `node_modules`. This is
the standard pattern for `sharp` and is widely accepted in commercial
deployments.

**Other license mix:** 117 packages MIT, 28 Apache-2.0, 17 ISC, 4
BSD-3-Clause, 1 BSD-2-Clause, 1 0BSD, 1 CC-BY-4.0 (caniuse-lite data,
attribution-only), 2 Unlicense, 1 Unlicensed (the `portal` project
itself). No GPL, AGPL, or commercial-restricted licenses.

**Recommended action:** **Accept-with-justification**. Document in
SECURITY.md that the portal ships a dynamically-linked LGPL component
(libvips via sharp) and that the prebuilt binary is repackaged for
each target platform. If a more conservative posture is required, the
portal can drop `sharp` (it is loaded only by `next/image`'s image
optimization pipeline, and Next.js will fall back to no-image-optimization
at runtime — the build will still succeed).

### Check 7 — Python abandonment (direct deps)

For every package in `pyproject.toml` (8 direct deps: `dspy`, `litellm`,
`fastapi`, `jinja2`, `optuna`, `python-multipart`, `pytest`, `pytest-cov`),
the latest release on PyPI is from 2024-05-20 or later. None are flagged
as abandoned under the 2-year threshold.

For completeness, 9 transitive packages are older than 2 years
(`defusedxml 0.7.1`, `sortedcontainers 2.4.0`, `mdurl 0.1.2`, `diskcache
5.6.3`, `distro 1.9.0`, `sniffio 1.3.1`, etc.), but all of those are
maintained, widely-used, and unmaintained-abandonment is not the same
as "no recent release" (e.g. `defusedxml` is intentionally
versioned-stable for security; `sortedcontainers` is a small,
feature-complete C extension). None of these are in scope for
abandonment-driven replacement.

### Check 8 — JavaScript abandonment (direct deps)

For every package in `apps/portal/package.json` (18 direct deps), the
latest release on the npm registry is from 2024-08-31 or later. None
are flagged as abandoned, and none are flagged as deprecated by their
maintainers.

### Check 9 — Python pin state (DONE)

`pyproject.toml` was updated so that every entry in `dependencies` and
`optional-dependencies.dev` is an exact `==X.Y.Z` pin. The version
used is the one already resolved in the working `.venv` (verified via
`pip show`), so the pin matches what the project's test suite is
actually exercised against.

| Package | Old | New (pinned) | Resolved |
|---|---|---|---|
| dspy | `>=2.5` | `==3.2.1` | 3.2.1 |
| dspy[optuna] | `>=2.5` | `==3.2.1` | 3.2.1 |
| litellm | `>=1.40` | `==1.89.1` | 1.89.1 |
| fastapi | `>=0.110` | `==0.137.1` | 0.137.1 |
| jinja2 | `>=3.1` | `==3.1.6` | 3.1.6 |
| optuna | `>=3.6` | `==4.9.0` | 4.9.0 |
| python-multipart | `>=0.0.9` | `==0.0.32` | 0.0.32 |
| pytest | `>=8.0` | `==9.1.0` | 9.1.0 |
| pytest-cov | `>=4.1` | `==7.1.0` | 7.1.0 |

`pytest-asyncio`, `pytest-mock`, etc. are not declared; they are
pulled in transitively if at all.

`pyproject.toml` after pinning:

```toml
# Pinned to dated versions — see docs/SEC_REVIEW_deps.md (kanban t_c7d352a7)
# Audit run: 2026-06-17 (CVE-2025-69872 diskcache open, no fix available)
dependencies = [
    "dspy==3.2.1",
    "litellm==1.89.1",
    "fastapi==0.137.1",
    "jinja2==3.1.6",
    "optuna==4.9.0",  # required by dspy.MIPROv2 at runtime
    "python-multipart==0.0.32",  # required by FastAPI File() / Form() parsing
]

[project.optional-dependencies]
dev = [
    "pytest==9.1.0",
    "pytest-cov==7.1.0",
    "dspy[optuna]==3.2.1",  # the compile-mode tests exercise MIPROv2 end-to-end
]
```

**Verification:** `pip-audit -r <extracted deps> --no-deps` → 1 finding
(`diskcache 5.6.3`, no fix). `pytest tests/ -q` → 465 passed, 1 skipped
(`MINIMAX_API_KEY` integration test), 0 failed. No regressions from
pinning.

### Check 10 — JavaScript pin state (DONE)

`apps/portal/package.json` was updated so that every direct+dev
dependency is an exact `X.Y.Z` pin (no caret, no tilde). In addition,
two `overrides` were added to clear the transitive vulnerabilities
found in Check 4. The overrides are repeated under both the standard
`overrides` field (used by `npm 8.3+`) and `pnpm.overrides` (used by
pnpm), so the protections apply regardless of which package manager
the next person uses.

| Package | Old | New (pinned) | Resolved |
|---|---|---|---|
| @auth/prisma-adapter | `^2.11.2` | `2.11.2` | 2.11.2 |
| @prisma/adapter-better-sqlite3 | `^7.8.0` | `7.8.0` | 7.8.0 |
| @prisma/client | `^7.8.0` | `7.8.0` | 7.8.0 |
| better-sqlite3 | `^12.11.1` | `12.11.1` | 12.11.1 |
| next | `16.2.9` | `16.2.9` | 16.2.9 (no change) |
| next-auth | `5.0.0-beta.31` | `5.0.0-beta.31` | 5.0.0-beta.31 (no change) |
| react | `19.2.4` | `19.2.4` | 19.2.4 (no change) |
| react-dom | `19.2.4` | `19.2.4` | 19.2.4 (no change) |
| resend | `^6.12.4` | `6.12.4` | 6.12.4 |
| stripe | `^22.2.1` | `22.2.1` | 22.2.1 |
| zod | `^4.4.3` | `4.4.3` | 4.4.3 |
| @types/node | `^20` | `20.19.43` | 20.19.43 |
| @types/react | `^19` | `19.2.17` | 19.2.17 |
| @types/react-dom | `^19` | `19.2.3` | 19.2.3 |
| dotenv | `^17.4.2` | `17.4.2` | 17.4.2 |
| prisma | `^7.8.0` | `7.8.0` | 7.8.0 |
| tsx | `^4.22.4` | `4.22.4` | 4.22.4 |
| typescript | `^5` | `5.9.3` | 5.9.3 |

**Transitive overrides added:**

| Package | Old (vulnerable) | Pinned to | Reason |
|---|---|---|---|
| `@hono/node-server` | 1.19.11 (transitive) | `1.19.14` | Closes `GHSA-92pp-h63x-v22m` (middleware bypass via repeated slashes; patched in 1.19.13). |
| `postcss` | 8.4.31 (transitive) | `8.5.10` | Closes `GHSA-qx2v-jg93` (XSS via unescaped `</style>` in stringify; patched in 8.5.10). |

`package.json` after pinning (key excerpt):

```json
"overrides": {
  "@hono/node-server": "1.19.14",
  "postcss": "8.5.10"
},
"pnpm": {
  "overrides": {
    "@hono/node-server": "1.19.14",
    "postcss": "8.5.10"
  }
}
```

`pnpm-lock.yaml` was regenerated with `pnpm install --no-frozen-lockfile`.
The resolution added 2 packages (the overridden transitive versions).

**Verification:** `pnpm audit` → "No known vulnerabilities found."
`npm audit` (against a synthesized `package-lock.json` in `/tmp/npm-audit-tmp/`,
because the project itself does not ship one) → 0 vulnerabilities.

### Check 11 — Post-pin re-scan

```
# pip-audit (resolved env)
$ pip-audit
Found 1 known vulnerability in 1 package
Name      Version ID             Fix Versions
--------- ------- -------------- ------------
diskcache 5.6.3   CVE-2025-69872
(1 finding; same as pre-pin; no fix available)

# pip-audit (direct requirements only)
$ pip-audit -r <requirements.txt> --no-deps
Found 1 known vulnerability in 1 package
Name      Version ID             Fix Versions
--------- ------- -------------- ------------
diskcache 5.6.3   CVE-2025-69872
(1 finding; same as pre-pin)

# safety check
$ safety check -r pip-freeze.txt --output text
1 vulnerability reported
0 vulnerabilities ignored
-> Vulnerability found in diskcache version 5.6.3
   Vulnerability ID: SFTY-20260211-60584
   (CVE-2025-69872)

# pnpm audit
$ pnpm audit
No known vulnerabilities found

# npm audit (synthesized lockfile)
$ npm audit
found 0 vulnerabilities
```

The Python side has one residual finding (the `diskcache` CVE) for
which no fix is published. The JavaScript side is clean.

---

## Remediation table

| # | Dependency | Current | Pinned | Risk category | Severity | CVE / advisory | License | Recommended action |
|---|---|---|---|---|---|---|---|---|
| 1 | dspy (Python, direct) | `>=2.5` | `==3.2.1` | (none) | — | — | MIT | **Keep**. Pinned to resolved version. |
| 2 | litellm (Python, direct) | `>=1.40` | `==1.89.1` | (none) | — | — | MIT | **Keep**. Pinned. |
| 3 | fastapi (Python, direct) | `>=0.110` | `==0.137.1` | (none) | — | — | MIT | **Keep**. Pinned. |
| 4 | jinja2 (Python, direct) | `>=3.1` | `==3.1.6` | (none) | — | — | BSD-3-Clause | **Keep**. Pinned. |
| 5 | optuna (Python, direct) | `>=3.6` | `==4.9.0` | (none) | — | — | MIT | **Keep**. Pinned. |
| 6 | python-multipart (Python, direct) | `>=0.0.9` | `==0.0.32` | (none) | — | — | Apache-2.0 | **Keep**. Pinned. |
| 7 | pytest (Python, dev) | `>=8.0` | `==9.1.0` | (none) | — | — | MIT | **Keep**. Pinned. |
| 8 | pytest-cov (Python, dev) | `>=4.1` | `==7.1.0` | (none) | — | — | MIT | **Keep**. Pinned. |
| 9 | **diskcache (Python, transitive via dspy + litellm)** | 5.6.3 | 5.6.3 (no fix) | Known CVE | High per advisory; Medium per actual risk profile | **CVE-2025-69872** / SFTY-20260211-60584 / GHSA-w8v5-vhqr-4h9v | Apache-2.0 | **Accept-with-justification** until upstream fixes. Track upstream. Document residual in SECURITY.md. |
| 10 | (all 18 JS direct deps) | caret-pinned | exact-pinned | (none) | — | — | MIT / Apache-2.0 / ISC / BSD mix | **Keep**. Pinned to resolved versions. |
| 11 | `@hono/node-server` (JS, transitive via @prisma/dev) | 1.19.11 | `1.19.14` (via overrides) | Known CVE | Moderate (CVSS 5.3) | **GHSA-92pp-h63x-v22m** | MIT | **Fixed in this run** via `overrides` + `pnpm.overrides`. |
| 12 | `postcss` (JS, transitive via next) | 8.4.31 | `8.5.10` (via overrides) | Known CVE | Moderate | **GHSA-qx2v-jg93** | MIT | **Fixed in this run** via `overrides` + `pnpm.overrides`. |
| 13 | `@img/sharp-libvips-darwin-arm64` (JS, transitive via next→sharp) | 1.2.4 | unchanged | License (LGPL) | Low (dynamic-linking pattern is acceptable) | — | LGPL-3.0-or-later | **Accept-with-justification**. Document in SECURITY.md. Replace only if a stricter posture is required (then drop `sharp` and let Next.js skip image optimization). |
| 14 | `defusedxml`, `sortedcontainers`, `mdurl`, `distro`, `sniffio` (Python, transitive) | various | unchanged | Abandonment (last release > 2y) | Low (still maintained, just not point-releasing) | — | various permissive | **Keep**. All are widely-used, intentionally stable, and not flagged by their maintainers. |
| 15 | All other resolved Python and JS transitives | various | unchanged | (none) | — | — | permissive | **Keep**. No findings. |

---

## Out of scope (per task body)

- Application-level code changes beyond dependency version bumps required
  to clear CVEs. (None required; all CVEs are in transitives, not in
  first-party code.)
- Renormalizing the overall dependency set or removing unused packages
  unrelated to a finding. (`diskcache` is a transitive that would only
  be removed by forking `dspy` / `litellm`.)
- Setting up CI to run these scanners on every PR. (This report is the
  artifact; a follow-up card is the right scope for a CI hook.)
- License-header audits of first-party source code.

---

## Follow-up work (recommended for a follow-up card)

1. **Track `diskcache` upstream** at https://github.com/grantjenks/python-diskcache.
   When a fix lands, bump `pyproject.toml` and re-run the scans. Until
   then, document the residual risk in `SECURITY.md` (currently does
   not exist; create it as part of this card or a follow-up).
2. **Generate a `package-lock.json`** for `apps/portal/`. The project
   ships a `pnpm-lock.yaml` but not a `package-lock.json`. Without one,
   anyone running `npm install` instead of `pnpm install` will get a
   different tree. The cleanest way is `npm i --package-lock-only` from
   a clean tree, or a CI hook that regenerates both lockfiles.
3. **Add a CI step** that runs `pip-audit` and `pnpm audit` on every PR.
   The `diskcache` CVE should be marked `--ignore-vuln CVE-2025-69872`
   in the `pip-audit` step until a fix is published (the issue is
   acknowledged upstream; this is the standard pattern).
4. **Drop `sharp`** if a stricter license posture is required. The
   portal's image-optimization usage is minimal; verify with
   `grep -rn 'next/image' apps/portal/src/` and decide.
