---
name: cns
description: Central Nervous System — atomized strategic bets with automated conflict detection and a `/spar` resolution ritual. Invoke with no argument to run the unified walk (reindex-if-needed → detect → spar). Also routes to sub-skills when the user is exploring or setting up.
---

# CNS — Central Nervous System

CNS is a workflow for maintaining strategic state as atomized "bets" (one bet per file) in a markdown vault, with automated conflict detection against vault edits, git commits, and GitHub PRs.

## When to use

- **`/cns` (no argument)** — run the unified walk: detect any bet edits since the last index, reindex if needed, run conflict detection, then walk `/spar`. This is the **default leader ritual** — one console, no workspace hopping.
- User says: "I want to organize my strategic decisions" / "my planning docs are out of sync" / "set up CNS" → see Sub-skills below.
- User asks how CNS works, what a bet looks like, or how the conflict-detection works → read this file.
- User isn't sure which sub-command to run → read this file.

## The unified walk (default `/cns` invocation)

The leader edits a bet in Obsidian. They want to know: **is the system in a consistent state, and is there anything I need to spar?** That used to require three context switches (Obsidian → terminal `cns reindex` + `cns detect` → Claude Code `/spar`). The unified walk collapses it to one invocation.

### Procedure

1. **Locate the vault.** Walk up from cwd looking for `.cns/config.yaml`. If none, ask the user where their vault is. Read the config to confirm `bets_dir`, `bets_index`, and `conflicts_file`.

2. **Check whether the bets index is fresh.** Shell out to:
   ```bash
   cns reindex --vault <vault> --check
   ```
   This compares the mtime of every `bet_*.md` against the mtime of `<bets_index>` (default `Brain/Bets/BETS.md`) and exits 0 if fresh, 1 if any bet file is newer than the index (or the index is missing). The CLI prints a one-line `fresh:` or `stale: ...` message — surface that to the user verbatim so they see *why* a reindex is happening.

3. **Reindex iff stale.** If the freshness check exits non-zero, run:
   ```bash
   cns reindex --vault <vault>
   ```
   Show the user the resulting `Wrote <path> (N active bets)` line so they know which bets ended up in the index.

   If the freshness check exits 0, **skip reindex** — printing "Index is fresh; skipping reindex." Don't waste the leader's attention on a no-op.

4. **Run detection.** Invoke the **`/cns-detect`** sub-skill (do NOT shell out to `cns detect` directly — chain to the skill so its summary formatting is consistent across entry points). The skill will print the conflicts summary (count, oldest, anything flagged "needs sparring").

5. **Walk `/spar`.** Invoke the **`/spar`** sub-skill. It reads `CONFLICTS.md`, walks each conflict one at a time, and (in vaults with execution config) walks pending reviews after the conflicts queue empties. If `/cns-detect` reported zero conflicts AND there are no pending reviews, `/spar` will short-circuit with "No open conflicts. Nothing to spar." — that's the success case for the walk.

### Constraints

- **Do NOT modify bet files inline.** This skill is a router: it calls `cns reindex --check`, then optionally `cns reindex`, then chains to `/cns-detect` and `/spar`. All bet mutations happen inside `/spar`'s well-defined resolution flow.
- **Do NOT skip `/cns-detect`** even if the index was fresh. A fresh index means no manual edits since the last detect, but external signals (git commits, GitHub PRs in `signal_sources`) may still produce new conflicts. Detect is cheap and idempotent; always run it.
- **Always surface the freshness check result.** The leader's mental model relies on knowing "did anything change?" — if you silently skip reindex, surface that you did.
- **If `cns reindex --check` itself errors** (e.g. no vault config), surface the error verbatim and stop. Don't try to recover by guessing a default vault path.

### Why the freshness check matters

The whole point of unifying the walk is that the leader stops thinking about the plumbing. Reindexing when nothing has changed is a no-op but adds noise to the conversation. Reindexing when something *has* changed is required for the detector to see the latest bet content. The `--check` exit code lets the skill make this decision without parsing markdown — the CLI is the source of truth.

## Sub-skills

- **`/cns-bootstrap`** — initialize CNS in a vault (`--blank` for empty, `--from-existing` to extract from existing docs)
- **`/bet`** — create a new bet (guided)
- **`/cns-detect`** — run conflict detection (one-shot or wired into automation)
- **`/spar`** — interactive conflict resolution + review queue walk
- **`/execute`** — dispatch role-scoped agents to do work for active bets

## Quick reference

```
.cns/config.yaml          # user config: roles, horizons, signal sources, automation
Brain/                    # configurable name
  Bets/
    BETS.md               # auto-generated index, grouped by owner role
    bet_<slug>.md         # one bet per file
  CONFLICTS.md            # detector output, sectioned by owner role
  Reviews/                # /execute review queue (per-leader once enabled)
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

- **User typed `/cns` with no argument** → run the unified walk above.
- User in a fresh vault → `/cns-bootstrap --blank`
- User has existing strategic docs → `/cns-bootstrap --from-existing <paths>`
- User wants to add a new bet → `/bet`
- User wants to see current conflicts only (no spar) → `/cns-detect`
- User wants to resolve open conflicts only (skip reindex/detect) → `/spar`
- User edited a bet manually and wants the index refreshed → `cns reindex` (CLI)
- User wants the system to do work on their bets → `/execute`

For full design see [docs/getting-started.md](../../docs/getting-started.md).

## Example: end-to-end walk

```
$ # leader just edited bet_ship_v1_blog.md in Obsidian
$ # in Claude Code:
/cns

# Skill: locating vault…
# Skill: checking freshness…
# CLI:   stale: 1 bet(s) newer than index: bet_ship_v1_blog.md
# Skill: reindexing…
# CLI:   Wrote /vault/Brain/Bets/BETS.md (4 active bets)
# Skill: chaining /cns-detect…
# /cns-detect: 2 open conflicts (1 CEO, 1 CTO). Oldest: 3 days. 1 flagged "needs sparring".
# Skill: chaining /spar…
# /spar: walks conflict 1 of 2 → leader picks [e] Edit → kill_criteria filled in → conflict drops out
# /spar: walks conflict 2 of 2 → leader picks [c] Confirm → last_reviewed bumped
# /spar: queue empty. Pending reviews: 0. Done.
```

One invocation, three actions, zero workspace hopping. That's the contract.
