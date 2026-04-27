# GigaBrain CNS — Central Nervous System

A **delegation console for leaders**. GigaBrain models your work like a company org structure: you set vision and strategic bets, your "executives" (role-scoped agents) execute independently, and only distilled briefs requiring your decision come back up. One central place to issue direction and ingest signal — never to read raw work product.

## Vision

GigaBrain is built for whoever leads a team — CEO, manager, tech lead, anyone who delegates to people or agents who can mostly run independently. The leader operates at the **vision and positioning** layer; subordinates handle implementation. The system grows with you: today a flat CEO → C-suite split, eventually a recursive tree (CTO spawns VPs spawns engineers) as load demands. See [CLAUDE.md](CLAUDE.md) for the full mental model.

## What it does

CNS turns scattered strategy docs (planning notes, todos, daily journals, memory files) into one-bet-per-file atoms with explicit kill criteria. A nightly detector compares your active bets against new vault edits, git commits, and GitHub PRs — and surfaces anything that contradicts an active bet. A `/spar` skill walks you through resolving conflicts one at a time. An `/execute` skill dispatches a role-scoped agent per bet to do the work and return a distilled brief.

## Why

Strategic state drifts. The strategy doc you wrote in March doesn't agree with the todo list you wrote in April, and neither agrees with the code you wrote yesterday. And the work itself drifts from the vision: things ship that nobody decided to ship, decisions get made in three places without each other knowing. CNS makes both kinds of drift visible and gives you a structured ritual to resolve them.

## Quick start

### 0. Set up an Obsidian vault (if you don't have one)

CNS operates on a **vault** — a folder of markdown files. [Obsidian](https://obsidian.md) is the recommended editor (free, local-first, no account), but any tool that edits `.md` files works. If you already have an Obsidian vault, skip ahead.

1. Install Obsidian from [obsidian.md](https://obsidian.md).
2. Create a folder anywhere on disk (e.g. `~/Documents/MyVault`).
3. Open Obsidian → **Open folder as vault** → pick that folder.
4. Recommended: `git init` inside the vault so CNS's reindex/detect output is version-controlled.

After bootstrap, your vault will look like this in Obsidian's sidebar:

```
MyVault/
├── Brain/
│   ├── Bets/
│   │   ├── BETS.md          ← auto-generated index, opens in Obsidian
│   │   └── bet_*.md         ← one bet per file
│   └── CONFLICTS.md         ← detector output, opens in Obsidian
└── .cns/
    └── config.yaml          ← hidden in Obsidian; edit from your terminal
```

Obsidian hides dotfile folders by default — that's fine. `.cns/` is managed by the `cns` CLI, not edited inside Obsidian. Everything under `Brain/` is normal markdown that you read, edit, and link to like any other note.

### 1. Install the Claude Code plugin

(gets you the `/cns`, `/cns-bootstrap`, `/cns-detect`, `/spar` skills)

```
/plugin marketplace add kunggaochicken/GigaBrain
/plugin install cns@cns
```

### 2. Install the Python CLI

(gets you `cns bootstrap | reindex | detect | validate`)

```bash
pip install git+https://github.com/kunggaochicken/GigaBrain.git
# (PyPI release coming in v0.2)
```

### 3. First-run flow

```bash
# In your vault (the folder you opened in Obsidian):
cd path/to/your/vault
cns bootstrap              # create .cns/config.yaml with default settings

# Write your first bet (copy the template):
cp /path/to/cns/templates/bet.md.template Brain/Bets/bet_my_first.md
$EDITOR Brain/Bets/bet_my_first.md
# (or open Brain/Bets/bet_my_first.md directly in Obsidian and edit there)

# Regenerate the index:
cns reindex

# Run detection:
cns detect

# Author bets, dispatch agents, review their output (all in Claude Code):
/bet                       # conversational bet authoring
/role-setup                # add CTO, CMO, etc. with workspaces and personas
/execute                   # dispatch role-scoped agents on active bets
/spar                      # walk conflicts, then review pending agent briefs
```

In Obsidian, refresh the file explorer (or just keep working — Obsidian picks up filesystem changes automatically) to see the new `BETS.md` and any `CONFLICTS.md` entries appear.

For interactive setup with a config wizard (instead of `cns bootstrap`'s defaults), use the `/cns-bootstrap` Claude Code skill.

Full walkthrough: [docs/getting-started.md](docs/getting-started.md)

## Design principle

**Single console, no workspace hopping.** The vault (`Brain/`) is the only place a user needs to look to see pending bets, conflicts, and review items — even when artifacts live in external repos. See [CLAUDE.md](CLAUDE.md).

## Status

v0.1 — early. Schema is versioned; breaking changes will ship migration scripts.

## Daily loop

```
/bet           author a strategic bet
/execute       dispatch role-scoped agents (CTO writes code, CMO drafts posts, ...)
/spar          walk conflicts + pending briefs in one session
```

Briefs land in `Brain/Reviews/<bet-slug>/brief.md` written at the leader's altitude — no diffs, no implementation noise. Accept promotes staged files into the role's workspaces; reject discards them. See [`docs/superpowers/specs/2026-04-26-execute-and-review-design.md`](docs/superpowers/specs/2026-04-26-execute-and-review-design.md) for the full design.

## License

MIT.
