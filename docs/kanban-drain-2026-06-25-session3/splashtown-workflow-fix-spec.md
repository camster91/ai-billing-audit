# splashtown — `.github/workflows/build-and-push.yml` failing 0s

**Task:** `t_5026c3b5` (ready, priority 2)
**Repository:** `splashtown-app` (currently no local checkout — the symlink `/Users/biancabienaime/projects/splashtown-app` → `/Users/biancabienaime/repos/splashtown-app` is broken; only `/Users/biancabienaime/projects/ashbi-portfolio-assets/splashtown` exists, which is for marketing screenshots)

## Why it's blocked

The fix needs to read the workflow file. No local checkout means the
fixing agent can't see `on: push`, `jobs:`, `steps:`, or recent run
logs.

## Diagnosis steps (when the repo is checked out)

```bash
# 1. Clone (or fix the symlink)
git clone https://github.com/ashbi/splashtown-app /Users/biancabienaime/repos/splashtown-app
cd /Users/biancabienaime/repos/splashtown-app

# 2. Look at the workflow
cat .github/workflows/build-and-push.yml

# 3. Get recent run logs
gh run list --workflow=build-and-push.yml --limit=5
gh run view --workflow=build-and-push.yml --log-failed

# 4. Common 0-second failure causes
```

## Common causes of 0-second failures

A workflow that fails in 0 seconds typically has a YAML/syntax error
or a `permissions:` / `on:` validation issue, not a runtime failure.

### Cause 1 — Invalid `on:` syntax

```yaml
# BAD — invalid types
on:
  push:
    branches: [main, develop
  pull_request:
    branches: main]

# GOOD
on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main]
```

YAML parser fails immediately → 0s.

### Cause 2 — Invalid `permissions:` key

```yaml
# BAD — invalid scope
permissions:
  contents: deploy  # not a valid scope (should be read/write/none)

# GOOD
permissions:
  contents: read
  packages: write
```

### Cause 3 — Missing `if:` condition or invalid `${{ }}` interpolation

```yaml
# BAD — unescaped brace in JSON
steps:
  - run: |
      echo "{"key": "value"}"

# GOOD — use heredoc or env var
steps:
  - run: |
      cat <<EOF > output.json
      {"key": "value"}
      EOF
```

### Cause 4 — Invalid matrix or anchor reference

```yaml
# BAD — undefined anchor
jobs:
  build:
    steps:
      - uses: actions/checkout@v4
        with:
          ref: *undefined_anchor  # <-- this fails YAML parse

# GOOD — define the anchor
.yes: &yes "yes"
jobs:
  build:
    steps:
      - uses: actions/checkout@v4
        with:
          ref: *yes
```

### Cause 5 — Permissions issue with `GITHUB_TOKEN`

If the workflow pushes to a registry (Docker Hub, GHCR), and the repo
settings disallow GitHub Actions from creating tokens:

```yaml
# Solution: Settings → Actions → General → Workflow permissions
# → Allow GitHub Actions to create and approve pull requests
# (and read/write packages if using GHCR)
```

## Diagnostic approach

```bash
# Lint the YAML locally
yamllint .github/workflows/build-and-push.yml

# Or use actionlint (more GitHub-specific)
brew install actionlint
actionlint .github/workflows/build-and-push.yml

# Validate the workflow against the GitHub schema
gh workflow view build-and-push.yml
```

## Fix template

After identifying the issue, the fix is usually:

1. Add missing brackets / quotes
2. Fix permissions keys
3. Escape interpolation properly
4. Add `permissions:` block at top
5. Test with `act` locally (optional):
   ```bash
   brew install act
   act push -W .github/workflows/build-and-push.yml --dryrun
   ```

## Acceptance criteria

- [ ] `yamllint .github/workflows/build-and-push.yml` passes (or 0 critical errors)
- [ ] `actionlint .github/workflows/build-and-push.yml` passes
- [ ] `gh run list --workflow=build-and-push.yml --limit=3` shows recent green runs
- [ ] Push to a test branch triggers the workflow and it completes in >0s
- [ ] Build artifact (Docker image) actually gets pushed

## Out of scope

- Refactoring the workflow into reusable actions
- Adding new triggers (schedule, workflow_call, etc.)
- Migrating to composite actions
- Updating other workflows (only