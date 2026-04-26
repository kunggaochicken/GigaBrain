---
title: PR test gate
date: 2026-04-26
status: draft
---

# PR test gate

Block merges to `main` until CI (pytest + lint) passes. Auto-format and auto-lint commits locally via `pre-commit` so PRs don't fail on style.

## Goals

- A PR cannot be merged into `main` if any required check fails.
- Tests run on Python 3.11, 3.12, and 3.13.
- Lint and format are enforced in CI and auto-applied locally on commit.
- Admins can bypass protection in emergencies.

## Non-goals

- Coverage thresholds, deploy gates, release automation. Out of scope.

## Components

### 1. GitHub Actions workflow — `.github/workflows/ci.yml`

Triggers: `pull_request` targeting `main`, and `push` to `main`.

Two jobs run in parallel:

- **`pytest`** — matrix over `python-version: ["3.11", "3.12", "3.13"]`. Steps: checkout → setup-python → `pip install -e ".[dev]"` → `pytest`. Each matrix leg appears as its own check (`pytest (3.11)`, `pytest (3.12)`, `pytest (3.13)`).
- **`lint`** — single job on Python 3.12. Steps: checkout → setup-python → `pip install ruff` → `ruff check .` → `ruff format --check .`.

Pip caching keyed on `pyproject.toml` to keep runs under ~30s steady-state.

### 2. Ruff configuration — `pyproject.toml`

Add to `[project.optional-dependencies].dev`: `ruff`, `pre-commit`.

Add a new section:

```toml
[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "W", "I", "B", "UP", "N"]
```

Rule set rationale: `E/F/W` (pycodestyle + pyflakes — style and real bugs), `I` (import order), `B` (likely-bug patterns), `UP` (modern syntax), `N` (PEP 8 naming).

### 3. Pre-commit hooks — `.pre-commit-config.yaml`

Two ruff hooks: `ruff` with `--fix` (auto-fixes lint), then `ruff-format` (formats). Both pinned to a recent stable rev.

Local one-time setup: `pip install pre-commit && pre-commit install`. After that, every `git commit` runs the hooks; commits with un-fixable lint errors are blocked.

### 4. Branch protection — `gh api`

Applied to `main`:

- `required_status_checks.contexts`: `["pytest (3.11)", "pytest (3.12)", "pytest (3.13)", "lint"]`
- `required_status_checks.strict`: `true` (branches must be up-to-date with `main` before merge)
- `enforce_admins`: `false` (admins can bypass in a pinch)
- `required_pull_request_reviews`: omitted (no review requirement — solo project)
- `restrictions`: `null`

Set via a single `gh api -X PUT repos/kunggaochicken/GigaBrain/branches/main/protection` call with a JSON body.

## Data flow

```
dev commits → pre-commit (ruff fix + format) → push → open PR
                                                        ↓
                                               GitHub Actions
                                                ┌───────┴───────┐
                                              pytest matrix    lint
                                                └───────┬───────┘
                                                        ↓
                                              all 4 checks pass?
                                                ┌───────┴───────┐
                                               yes             no
                                                ↓               ↓
                                            merge button     merge blocked
                                              enabled        (admin can override)
```

## Failure modes

- **Pre-commit not installed locally** → CI lint job catches it; PR blocked until pushed fix.
- **New Python version released** → matrix doesn't auto-update; intentional. Add it explicitly when ready.
- **Required check renamed** (e.g., we change matrix versions) → branch protection still references the old name and blocks merges. Mitigation: when changing the matrix, update the protection rule in the same PR.
- **`gh` not authenticated as admin** → `gh api` PUT returns 403. Caller must run `gh auth status` and confirm admin role first.

## Testing

Manual verification:

1. Open a throwaway PR that breaks a test → confirm `pytest` checks go red and merge button is disabled.
2. Open a throwaway PR that breaks formatting → confirm `lint` check goes red.
3. Open a clean PR → confirm all 4 checks go green and merge button enables.
4. As admin, confirm the "merge without waiting for requirements" option appears (the bypass).

No automated tests for the workflow itself — it's config.

## Rollout

Single PR containing: workflow, ruff config, pre-commit config, pyproject changes. Branch protection applied immediately after merge (chicken-and-egg: can't enforce a check that doesn't exist on `main` yet).
