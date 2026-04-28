# Changelog

All notable changes to GigaBrain CNS are documented here. The project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
