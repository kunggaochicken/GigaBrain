---
name: cns
description: Central Nervous System — atomized strategic bets with automated conflict detection and a `/spar` resolution ritual. Use when the user wants to set up CNS, ask about it, or doesn't know which sub-command they need.
---

# CNS — Central Nervous System

CNS is a workflow for maintaining strategic state as atomized "bets" (one bet per file) in a markdown vault, with automated conflict detection against vault edits, git commits, and GitHub PRs.

## When to use

- User says: "I want to organize my strategic decisions" / "my planning docs are out of sync" / "set up CNS"
- User asks how CNS works, what a bet looks like, or how the conflict-detection works
- User isn't sure which sub-command to run

## Sub-skills

- **`/cns-bootstrap`** — initialize CNS in a vault (`--blank` for empty, `--from-existing` to extract from existing docs)
- **`/cns-detect`** — run conflict detection (one-shot or wired into automation)
- **`/spar`** — interactive conflict resolution

## Quick reference

```
.cns/config.yaml          # user config: roles, horizons, signal sources, automation
Brain/                    # configurable name
  Bets/
    BETS.md               # auto-generated index, grouped by owner role
    bet_<slug>.md         # one bet per file
  CONFLICTS.md            # detector output, sectioned by owner role
```

## Bet file shape

```yaml
---
name: <short title>
status: active | superseded | killed | done
owner: <role id>
horizon: this-week | this-month | this-quarter | strategic
kill_criteria: <what would flip this> | "unspecified — needs sparring"
last_reviewed: YYYY-MM-DD
---

## The bet
## Why
## What would change this
## Open threads
## Linked
## Tombstone   ← appended on supersede/kill
```

## Decision tree for the model

- User in a fresh vault → `/cns-bootstrap --blank`
- User has existing strategic docs → `/cns-bootstrap --from-existing <paths>`
- User wants to see current conflicts → `/cns-detect`
- User wants to resolve open conflicts → `/spar`
- User edited a bet manually and wants the index refreshed → `cns reindex` (CLI)

For full design see [docs/getting-started.md](../../docs/getting-started.md).
