# Changelog

All notable changes to GigaBrain CNS are documented here. The project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
