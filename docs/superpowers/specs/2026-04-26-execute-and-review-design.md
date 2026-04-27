# GigaBrain — `/execute` + review queue + role workspaces (v1 design)

**Status:** Draft for review
**Date:** 2026-04-26
**Scope:** v1 of the leader-delegation execution loop. Adds `/execute`, `/bet`, `/role-setup`, extends `/spar`, adds role workspace permissions, and adds a review queue under the vault.

---

## 1. Vision and framing

GigaBrain is a delegation console for a leader (canonical example: CEO). The leader issues vision and strategic bets; role-scoped agents (CTO, CMO, CPO, etc.) execute independently and return only **distilled briefs** the leader needs to make decisions on. The leader does not read raw work product. See [`CLAUDE.md`](../../../CLAUDE.md) for the full mental model.

This v1 implements **one level** of the delegation tree: top-level leader → C-suite. The schema preserves hooks for an eventually-recursive tree (CTO → VPs → engineers); recursive dispatch is tracked in [issue #9](https://github.com/kunggaochicken/GigaBrain/issues/9).

**The leader's loop in v1:**

```
/bet           author a bet
/execute       dispatch role-scoped agents on active bets
/spar          walk conflicts, then walk briefs; accept/reject/supersede
```

All three rituals stay inside the vault. No workspace hopping (see "Single console" principle in `CLAUDE.md`).

---

## 2. Architecture overview

```
   ┌────────────────┐                              ┌────────────────────────────┐
   │  CEO writes    │                              │  Brain/Reviews/<bet-slug>/ │
   │  bets (/bet)   │                              │   ├── brief.md ◀── what    │
   └────────────────┘                              │   │      CEO reads         │
            │                                      │   ├── files/ ◀── work      │
            ▼                                      │   │      product mirror    │
   ┌────────────────┐    per-bet, scoped to       │   └── transcript.md        │
   │  /execute      │──▶  the bet's owner role ──▶│       (audit only)         │
   │  (dispatcher)  │    (CTO, CMO, CPO, …)       └────────────────────────────┘
   └────────────────┘                                            │
            ▲                                                    ▼
            │                                          ┌────────────────────┐
            │                                          │  /spar walks both: │
   vault ──▶│  cns detect ──▶ CONFLICTS.md ──────────▶│   - conflicts      │
   git   ──▶│                                          │   - briefs         │
   PRs   ──▶│  also re-runs against staged files       │  decides: accept,  │
            │  on each /spar visit (delta vs snapshot) │  reject, supersede │
            └──────────────────────────────────────────└────────────────────┘
```

**Three contracts:**

1. **`/execute`** picks active bets without a pending review, dispatches one agent per bet scoped to that bet's role's workspaces + tool allowlist. The agent stages work product in `Brain/Reviews/<bet-slug>/files/` and writes a `brief.md` at the leader's altitude. The brief is the primary artifact; `files/` is receipts.
2. **Detector reuse.** A new signal source `staged_review` plugs into the existing `cns.detector.detect_conflicts()` so each brief gets a related-bets snapshot at write time and a refreshed delta on every `/spar` visit.
3. **`/spar`** walks `CONFLICTS.md` first (existing behavior unchanged), then walks `Brain/Reviews/`. Reject = archive the staging dir. Accept = move files into the workspace, optionally close the bet, optionally supersede contradicted bets.

`/spar` remains the only writer of bet `status` fields. `/execute` never edits bets.

---

## 3. Config schema (`.cns/config.yaml`)

### New top-level section

```yaml
execution:
  reviews_dir: Brain/Reviews          # v1: one queue (top-level leader)
  top_level_leader: ceo               # whose queue Brain/Reviews/ belongs to
  default_filter: pending             # /execute default: bets without staged review
  artifact_max_files: 50              # safety cap per agent run
```

### Role schema (extended)

Each role grows four optional fields. Bare `{id, name}` roles still parse (backward compat).

```yaml
roles:
  - id: ceo
    name: CEO
    reports_to: null                  # NEW — root of the org tree
    workspaces: []                    # NEW — leader doesn't execute, only reviews
    tools: {}                         # NEW
    persona: |                        # NEW — system-prompt fragment
      You are the CEO. Issue vision, not implementation.

  - id: cto
    name: CTO
    reports_to: ceo
    workspaces:
      - path: ~/code/myapp            # absolute, ~-expanded
        mode: read-write
      - path: ~/code/myapp-infra
        mode: read-only
      - path: Brain/Engineering       # vault-relative, anchored at vault root
        mode: read-write
    tools:
      bash_allowlist:
        - "pytest"
        - "ruff *"
        - "mypy *"
        - "git status"
        - "git diff *"
      web: false
    persona: |
      You are the CTO. Write production-quality code with tests. Stage changes
      in Brain/Reviews/<bet-slug>/files/ mirroring the workspace tree. When done,
      produce brief.md at the CEO's altitude: what shipped, what blocks remain,
      what positioning call (if any) the CEO needs to make. Do not include diffs
      in the brief — link to files/ for receipts.
```

### Pydantic additions (`cns/models.py`)

```python
class Workspace(BaseModel):
    path: str
    mode: Literal["read-only", "read-write"]

class ToolPolicy(BaseModel):
    bash_allowlist: list[str] = []
    web: bool = False

class RoleSpec(BaseModel):
    id: str
    name: str
    reports_to: Optional[str] = None
    workspaces: list[Workspace] = []
    tools: ToolPolicy = Field(default_factory=ToolPolicy)
    persona: Optional[str] = None

class ExecutionConfig(BaseModel):
    reviews_dir: str = "Brain/Reviews"
    top_level_leader: str
    default_filter: Literal["pending", "all"] = "pending"
    artifact_max_files: int = 50

class Config(BaseModel):
    # …existing fields…
    execution: Optional[ExecutionConfig] = None  # required only when /execute runs
```

### New validators on `Config`

- `reports_to` references must resolve to existing role ids or be `null`.
- The `reports_to` graph is acyclic and has exactly one root.
- `execution.top_level_leader` matches that unique root.
- `workspaces[*].path`: vault-relative paths anchored at vault root; absolute paths kept as-is; `~` expanded at use-time.

### Schema versioning

Optional top-level `schema_version: 2`. Loader treats absent as v1 (legacy) and applies safe defaults. v2 means the user opted into execution-aware config.

---

## 4. Review entry schema (`Brain/Reviews/<bet-slug>/`)

Each pending review is its own directory:

```
Brain/Reviews/
└── ship_v1_blog/                  # = bet slug, sans bet_ prefix
    ├── brief.md                   # PRIMARY: what the leader reads
    ├── files/                     # mirror of workspace paths the agent touched
    │   └── code/website/posts/v1-launch.md
    └── transcript.md              # full agent transcript, audit-only
```

### `brief.md` shape (the contract — `/spar` parses these fields)

```markdown
---
bet: bet_ship_v1_blog.md
owner: cmo
agent_run_id: 2026-04-26T15-32-04Z
status: pending                    # pending | accepted | rejected
proposed_closure: true             # agent's "ready to close" flag
related_bets_at_write:             # snapshot from /execute time
  contradicts: []
  same_topic_active: [bet_press_outreach.md]
  same_topic_historical: [bet_v0_blog_killed.md]
files_touched:
  - path: ~/code/website/posts/v1-launch.md
    action: created
    bytes: 4127
verification:
  - cmd: vale ~/code/website/posts/v1-launch.md
    exit: 0
---

## TL;DR for the CEO
One paragraph at vision altitude. What was decided. What's on the table.

## What I did
2-4 bullets. No diffs. Link to files/ for receipts.

## Why this satisfies the bet
Cite the bet's `## The bet` and `## Why`. Call out anything you couldn't address.

## Decisions I need from you
Numbered list. Each item is a positioning call only the leader can make.
If empty, write "None — proceed to accept or reject."

## Blocks remaining
Anything you couldn't finish, with a one-line "what would unblock me."

## Proposed next state of the bet
- [x] mark `done` (proposed_closure: true)
- [ ] supersede with: <new bet name> — only if work uncovered a different call

## Receipts
- See `files/` for the work product.
- See `transcript.md` for the full session.
```

### Status lifecycle

`pending` (just written) → `accepted` (files moved into workspace, dir archived to `Brain/Reviews/.archive/<timestamp>_<slug>/`) **or** `rejected` (dir archived, no workspace changes).

### Staging path mapping rule

The staging mirror under `files/` strips workspace-path prefixes so the same relative tree appears under every review dir:

- Absolute paths: drop the leading `/`. `~/code/myapp/src/foo.py` → `files/code/myapp/src/foo.py`.
- Vault-relative paths: keep as-is. `Brain/Marketing/post.md` → `files/Brain/Marketing/post.md`.

`/spar` accept reverses the mapping using the workspace declarations from `config.yaml` to know which root each staged path belongs to. `files_touched[].path` in the brief frontmatter always carries the **original workspace path**, not the staged path, so the leader sees the real destination.

### Invariants

- **One review dir per bet, not per run.** A re-run on the same bet replaces the staged dir; `transcript.md` keeps history if needed.
- **No diffs in `brief.md` body.** Diffs live in `files/` (and `transcript.md`). Frontmatter `files_touched` lists paths only.
- **`Decisions I need from you`** is the load-bearing section. Empty → low-friction accept. Non-empty → real sparring.

---

## 5. `/execute` — dispatcher and agent envelope

### Skill surface (`skills/execute/SKILL.md`)

```
/execute              → default: all active bets without a pending review
/execute --all        → all active bets, even those with pending reviews (replaces)
/execute <bet-slug>   → single bet
/execute --owner cto  → all active bets owned by a specific role
/execute --dry-run    → list what would run, don't dispatch
```

### Procedure

1. **Locate vault and load config.** Walk up for `.cns/config.yaml`. Validate `execution.top_level_leader`.
2. **Build the bet queue.** `cns.bet.list_bets(status=ACTIVE)`, then filter:
   - Default: drop bets with `Brain/Reviews/<slug>/brief.md` where `status: pending`.
   - `--all`: keep them; new run replaces the staged dir.
   - `--bet <slug>` or `--owner <id>`: scope further.
3. **Resolve role for each bet.** Look up `bet.owner` in `config.roles`. If owner has no `workspaces`, skip with a warning (the leader role is a valid owner only for bets that don't need execution).
4. **Per bet, dispatch one agent.** Sequential in v1; parallel deferred to [issue #8](https://github.com/kunggaochicken/GigaBrain/issues/8). Each dispatch:
   - Build agent system prompt: role's `persona` + standard scaffolding (where to stage, brief schema, the bet body).
   - Build tool envelope (see "Enforcement" below).
   - Build agent input: bet's full markdown body + the related-bets snapshot (computed by running `cns.detector.detect_conflicts()` against the bet's name/description over all bets active+historical).
   - Invoke via the Agent tool with a custom subagent type carrying the role-specific config.
5. **Capture output.** Agent must end with `Brain/Reviews/<slug>/brief.md` written, optionally `files/...`. Dispatcher validates the brief parses against the schema; on failure, the run is marked `failed` in frontmatter and reported to the user.
6. **Print a summary.** "Dispatched 4 bets, 3 produced briefs, 1 failed (parse error in brief.md). Run /spar to review."

### Enforcement of role workspaces and tool allowlist

The dispatched agent runs in a Claude Code subagent context. Two enforcement mechanisms:

- **Pre-tool-use hook (path enforcement).** Intercepts every `Edit`, `Write`, `Bash`. For Edit/Write, checks the target path:
  - Inside a `read-write` workspace → allow.
  - Inside `Brain/Reviews/<bet-slug>/files/` (the staging mirror) → always allow.
  - Otherwise → block with an instruction to stage under `Brain/Reviews/<slug>/files/<original-path>`.
  - For Read, allow `read-only` and `read-write` workspaces, plus the bet file and `Brain/Bets/`.
- **Pre-tool-use hook (Bash allowlist).** Parse the command, glob-match the leading token against `tools.bash_allowlist`. Block on miss. `cwd` forced to a read-write workspace path or staging dir.

Hook configs are generated per-run at `.cns/.agent-hooks/<bet-slug>.json` and cleaned up after the run.

### What `/execute` does NOT do

- Never edits the bet file itself (status, last_reviewed). That is `/spar`-only.
- Never moves files into the actual workspace. That is `/spar`-on-accept.
- Never opens git branches, never commits. v1 scope; deferred to [issue #11](https://github.com/kunggaochicken/GigaBrain/issues/11).

---

## 6. `/spar` extensions

The existing conflicts walk is unchanged. After it finishes (or if there were no conflicts), the skill enters **Phase 2: reviews**.

### Phase 2 procedure

1. Load `Brain/Reviews/*/brief.md` where `status: pending`. Sort oldest-first by `agent_run_id`.
2. For each review:
   - **Re-run detector** against `files/` to compute "delta since snapshot" vs `related_bets_at_write`.
   - **Display:** bet name + owner + the bet's `## The bet` and `## Why`; the brief's `## TL;DR for the CEO` and `## Decisions I need from you`; related bets (snapshot + delta, highlighting NEW contradictions); verification frontmatter results; `files_touched` paths (no diffs unless asked).
   - **Ask:**
     ```
     [a] Accept       — promote files/ into workspaces, archive review
     [r] Reject       — archive review, no workspace changes
     [e] Edit-and-rerun — append reviewer notes to brief.md, re-dispatch /execute
     [d] Defer        — set deferred_until on the bet, keep review pending
     [v] View diff    — show files/ contents and re-prompt
     [q] Quit
     ```
   - **If accepted AND `proposed_closure: true`:** ask "Mark bet as done?" [y/n] (default y).
   - **If accepted AND any contradicting active bets in snapshot+delta:** ask "This work supersedes [bet_X, bet_Y] — handle them?"
     ```
     [s] Supersede each (existing /spar supersede flow)
     [k] Kill each
     [n] No, leave them
     ```
   - **Apply:**
     - **Accept:** copy `Brain/Reviews/<slug>/files/<path>` → `<path>`; set brief frontmatter `status: accepted`; `mv` review dir to `Brain/Reviews/.archive/<timestamp>_<slug>/`; if user opted, mark bet `done` and update `last_reviewed`; if user opted, supersede/kill contradicted bets via existing flow.
     - **Reject:** set `status: rejected`; `mv` to `.archive`. No workspace changes. Bet unchanged.
     - **Edit-and-rerun:** append `## Reviewer notes` section to `brief.md`; re-dispatch `cns execute --bet <slug>` (replaces staged dir).
     - **Defer:** set `bet.deferred_until`; review stays in place.
3. **Final commit prompt** (existing pattern): "I made N edits to bet files / accepted M reviews / archived K. Commit as `chore(brain): spar session YYYY-MM-DD`?"

### Invariants preserved

- `/spar` remains the only writer of bet `status`.
- `last_reviewed` updates on accept (parallel to conflict-confirm).
- Reject does not update `last_reviewed`.

---

## 7. `/bet` — conversational bet authoring

Calls a new `cns.bet.create_bet()` primitive that `/spar`'s supersede path also uses.

```
/bet
  → "What's the bet? (1-2 sentences)"
  → "Whose call is this?" — multiple choice from config.roles
  → "Horizon?" — multiple choice from config.horizons keys
  → "Confidence?" [low/medium/high]
  → "What would change this? (kill_criteria — required, can't skip)"
  → "Does this supersede an existing bet?" [n / pick from active bets]
  → derives slug from name (lowercase, snake_case, dedup against existing files)
  → writes Brain/Bets/bet_<slug>.md via cns.bet.write_bet()
  → if supersedes: appends ## Tombstone to old bet, sets old.status=superseded
  → runs `cns reindex`
  → prints "Wrote bet_<slug>. Run /execute --bet <slug> to dispatch."
```

The `kill_criteria` prompt is required — no skip path. This is the primary win over `cp template && $EDITOR` (which leaves `kill_criteria: unspecified — needs sparring` as the default).

---

## 8. `/role-setup` — role authoring and editing

Operations:

- **Add:** pick from `templates/roles/<name>.yaml` or "blank"; walk fields prefilled from template; validate; append to `.cns/config.yaml`; re-validate full config (cycle + single-root checks).
- **Edit:** pick existing role; walk fields prefilled with current values.
- **Delete:** offered if no active bets are owned by the role and no other role `reports_to` it.

Uses `ruamel.yaml` (round-trip YAML) instead of `yaml.safe_dump` so existing comments and ordering survive. New dep added to `pyproject.toml`.

### New directory: `templates/roles/`

Ships with nine starter templates: `ceo.yaml`, `cto.yaml`, `cmo.yaml`, `cpo.yaml`, `chief-scientist.yaml`, `vp-engineering.yaml`, `engineer.yaml`, `marketing-lead.yaml`, `designer.yaml`. Each carries sensible `bash_allowlist` defaults and a starter `persona`.

---

## 9. CLI surface (`cns/cli.py`)

The interactive skills are thin shells over CLI primitives, so tests cover the CLI and the surface area stays small.

```
cns execute [--bet <slug>] [--owner <id>] [--all] [--dry-run]
cns reviews list
cns reviews accept <slug> [--mark-done] [--supersede <bet>...]
cns reviews reject <slug>
cns roles list                          # prints role tree indented by reports_to
cns execute init                        # adds execution{} block to existing configs
```

---

## 10. New module layout

```
cns/
├── (existing) bet.py, cli.py, config.py, conflicts.py, daily_report.py,
│              detector.py, index.py, models.py, signals.py
├── execute.py          # NEW — dispatcher, agent envelope builder
├── reviews.py          # NEW — brief schema, read/write, accept/reject ops
├── roles.py            # NEW — role tree validation, workspace path resolution
└── hooks.py            # NEW — generates per-run hook configs for path/Bash enforcement
```

---

## 11. Testing

Mirrors the existing `tests/` style (`tests/fixtures/sample_vault/`):

- **Unit:** `roles.py` tree validation (cycles, multi-root, dangling `reports_to`); `reviews.py` brief parse/serialize round-trip; `hooks.py` allowlist matcher (path inside/outside workspace, glob match on Bash commands).
- **Integration:** `cns execute --dry-run` against a fixture vault → asserts the per-bet plan. `cns reviews accept` against a fixture review dir → asserts files moved + archive created. End-to-end `/spar` Phase 2 walk via a transcript fixture.
- **No live agent invocation in tests.** The dispatcher's `Agent`-tool call path is mocked; tests assert the prompt and hook payload it would have sent.

---

## 12. Migration

- Existing vaults keep working. Bare `roles: [{id, name}]` parses (defaults applied). The `execution{}` block is required only when `cns execute` runs; if absent, the CLI prints "Run `cns execute init`" and exits cleanly.
- `cns execute init`: adds the `execution{}` block, infers `top_level_leader` from the unique `reports_to: null` role, creates `Brain/Reviews/`.
- Bet files are unchanged — no bet-level migration.

---

## 13. Plugin manifest

`.claude-plugin/plugin.json` registers the three new skills (`execute`, `bet`, `role-setup`) so `/plugin install cns@cns` picks them up.

---

## 14. Out of scope (deferred to v2+)

Each tracked as a separate GitHub issue:

- [#8 — Parallel /execute dispatch](https://github.com/kunggaochicken/GigaBrain/issues/8)
- [#9 — Recursive sub-delegation (CTO spawns engineer agents)](https://github.com/kunggaochicken/GigaBrain/issues/9)
- [#10 — Per-leader review queues (`Brain/Reviews/<leader-id>/`)](https://github.com/kunggaochicken/GigaBrain/issues/10)
- [#11 — Web and git tools for /execute agents](https://github.com/kunggaochicken/GigaBrain/issues/11)
- [#12 — /execute cost controls](https://github.com/kunggaochicken/GigaBrain/issues/12)

---

## 15. Open questions / risks

- **Hook enforcement reliability.** The path/Bash hooks are the trust boundary for the agent. If a hook bug lets the CTO-agent write to `~/code/myapp` directly (instead of staging), the accept/reject UX collapses. Mitigation: tests assert blocking behavior at the boundary; hook failures fail-closed (block the call) rather than fail-open.
- **Brief quality at low altitude.** The agent might write a brief that's secretly a diff in prose. Mitigation: persona explicitly instructs against diffs in the brief; we'll iterate on personas after seeing real output.
- **Staging-vs-real divergence for code repos.** An agent that runs `pytest` against `Brain/Reviews/<slug>/files/` might pass tests that fail when the file is actually placed at its real workspace path (because of import siblings the staging dir doesn't have). Mitigation: for code repos, the agent's bash `cwd` is the real workspace; the agent edits via the staging path, but the test command runs from the workspace root. We accept some risk here for v1; revisit if it bites.
- **`ruamel.yaml` dep.** Adds a runtime dep just to preserve YAML comments during `/role-setup` edits. Acceptable, but if it causes friction, we can fall back to "rewrite without comments and warn user" for v1 and treat round-trip preservation as a nice-to-have.
