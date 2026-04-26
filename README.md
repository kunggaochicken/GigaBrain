# GigaBrain CNS — Central Nervous System

Atomized strategic bets with automated conflict detection for markdown vaults.

## What it does

CNS turns scattered strategy docs (planning notes, todos, daily journals, memory files) into one-bet-per-file atoms with explicit kill criteria. A nightly detector compares your active bets against new vault edits, git commits, and GitHub PRs — and surfaces anything that contradicts an active bet. A `/spar` skill walks you through resolving conflicts one at a time.

## Why

Strategic state drifts. The strategy doc you wrote in March doesn't agree with the todo list you wrote in April, and neither agrees with the code you wrote yesterday. CNS makes that drift visible and gives you a structured ritual to resolve it.

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

# Resolve conflicts interactively (in Claude Code):
/spar
```

In Obsidian, refresh the file explorer (or just keep working — Obsidian picks up filesystem changes automatically) to see the new `BETS.md` and any `CONFLICTS.md` entries appear.

For interactive setup with a config wizard (instead of `cns bootstrap`'s defaults), use the `/cns-bootstrap` Claude Code skill.

Full walkthrough: [docs/getting-started.md](docs/getting-started.md)

## Status

v0.1 — early. Schema is versioned; breaking changes will ship migration scripts.

## License

MIT.
