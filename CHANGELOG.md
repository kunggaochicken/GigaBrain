# Changelog

All notable changes to GigaBrain CNS are documented here. The project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased

### Added — PreToolUse hook executor (issue #30)
- New CLI entry point `cns-hook-pretooluse` (and `python -m cns.hook_executor`):
  a Claude Code PreToolUse hook that reads the per-bet descriptor at
  `.cns/.agent-hooks/<slug>.json` and emits an allow/deny verdict for the
  tool call piped to its stdin.
- Enforcement matrix: `Edit`/`Write`/`MultiEdit`/`NotebookEdit` outside the
  staging dir → deny; `WebFetch` to a host not in `tools.web_allowlist` →
  deny; `WebFetch` when `tools.web: false` → deny; `WebSearch` when
  `tools.web: false` → deny; `Bash` commands not matching
  `tools.bash_allowlist` → deny. Read-style tools (Read/Glob/Grep) pass
  through.
- Active-bet resolution at hook time, in priority order: `$CNS_ACTIVE_BET`
  env var (paired with `$CNS_VAULT_ROOT`) → sentinel file at
  `<vault>/.cns/.agent-hooks/.active` → single-descriptor auto-detect →
  open mode (no enforcement). Open mode means the hook is safe to install
  globally — it only kicks in during an `/execute` run.
- New `cns hook-active set <slug>` / `cns hook-active clear` CLI commands
  for the `/execute` skill to manage the sentinel across each per-bet
  Agent invocation.
- New install template `templates/claude-settings.hook.json.template` and
  walkthrough `docs/installing-hook-executor.md`.
- `skills/execute/SKILL.md` updated: the v0.2 prompt-enforcement-only
  stanza is replaced with v0.3 hook-enforcement instructions.

## v0.4.0 (2026-04-26)

### Added — recursive sub-delegation (issue #9)
- A leader-agent mid-run (e.g. the CTO running a top-level bet) can now spawn
  its own subordinates by calling `cns execute --from-leader <self> --bet
  <sub-slug>`. The dispatcher returns a per-agent envelope routed into
  `Brain/Reviews/<self-id>/<sub-slug>/`, NOT the flat top-level queue —
  sub-agent briefs land in their direct leader's queue and propagation up
  the tree is an explicit choice (no auto-bubble).
- New CLI flags on `cns execute`: `--from-leader <role-id>`, `--chain
  '<json-pairs>'`, `--session-spend '<usd>'`. The chain is an ordered list of
  `[role_id, bet_slug]` pairs from the top-level leader through the calling
  leader; the dispatcher uses it for cycle and depth detection.
- `ExecutionConfig.max_dispatch_depth: int = 3` (validated `>= 1`). Default 3
  matches the canonical CEO -> CTO -> VP-Eng -> engineer chain in the vision
  doc. Configurable via `.cns/config.yaml`.
- New `DispatchSkipReason` values: `role_not_subordinate`, `depth_limit`,
  `cycle_detected`. Cycle detection rejects any role appearing twice in the
  chain; same bet slug repeating across different roles is a legitimate
  escalation pattern, NOT a cycle.
- `cns.roles.subordinates_of(roles, leader_id)` returns direct reports
  (one hop), distinct from the existing transitive `get_subordinates`.
- Budget propagation: per_session_usd_max is global across the recursion
  (the running session-spend threads through `--session-spend`). Per-run cap
  applies to each individual sub-agent. Per-role-daily applies to the
  sub-role, not to the calling leader.
- `skills/execute/SKILL.md` documents the sub-delegation contract: when to
  reach for it, how to author the sub-bet, what the chain / session-spend
  flags mean, and the full refusal table.

## v0.3.0 (2026-04-26)

### Added
- `/execute` cost controls (issue #12):
  - Per-agent token usage and dollar cost are persisted to `Brain/Reviews/<slug>/brief.md` frontmatter under a new `cost:` block (model, input/output/cache token counts, USD as a string-quoted Decimal).
  - `execution.budgets` config: `per_run_usd_max`, `per_session_usd_max`, and `per_role_daily_usd_max` (rolling-24h cap per role id). Dispatcher refuses bets whose estimate would breach any cap, with a clear refusal message.
  - `cns execute --estimate` flag: prints projected per-bet input/output tokens and dollar cost (using the role's historical median output as a baseline), then a session total. Does not dispatch.
  - `cns reports cost --since <date> [--until <date>] [--by role|bet|day]`: aggregates spend across the active queue and `.archive/`.
  - `/spar` Phase 2 review walk now surfaces the `[$X.YY]` cost tag inline; `cns reviews list` shows the same.
- `cns/pricing.py`: per-model USD rate table for Opus 4.7 / Sonnet 4.6 / Haiku 4.5 (input, output, cache read, cache write 5m/1h). All math in `Decimal`. Rates dated 2026-04-26 — re-verify quarterly.

### Notes
- Brief frontmatter is backwards-compatible: pre-v0.3 briefs without a `cost:` block load fine.
- The brief walker (`cns.reviews.iter_all_briefs`) recurses with `**/brief.md` so it works with both v0.2's flat layout and any future per-leader layout (`Brain/Reviews/<leader-id>/<slug>/brief.md`).

## v0.2.0 (2026-04-26)

### Added
- `/execute` skill: dispatches role-scoped agents per active bet
- `/bet` skill: conversational bet authoring with `kill_criteria` enforcement
- `/role-setup` skill: add/edit/delete roles with workspace + persona templates
- `/spar` Phase 2: walks pending review queue after conflicts
- `cns execute`, `cns execute init`, `cns reviews list|accept|reject`, and `cns roles list` CLI commands
- 9 role templates (ceo, cto, cpo, cmo, chief-scientist, vp-engineering, engineer, designer, marketing-lead) plus an extended config template
- Schema v2: roles gain `reports_to` / `workspaces` / `tools` / `persona`; new `execution` block

### Known limitations
- Hook executor not shipped — see #20
- `solo-founder` preset bricks `cns execute init` — see #19
- No automatic v1 → v2 vault migration; fresh installs only
