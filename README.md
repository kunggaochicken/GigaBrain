# CNS — Central Nervous System

Atomized strategic bets with automated conflict detection for markdown vaults.

## What it does

CNS turns scattered strategy docs (planning notes, todos, daily journals, memory files) into one-bet-per-file atoms with explicit kill criteria. A nightly detector compares your active bets against new vault edits, git commits, and GitHub PRs — and surfaces anything that contradicts an active bet. A `/spar` skill walks you through resolving conflicts one at a time.

## Why

Strategic state drifts. The strategy doc you wrote in March doesn't agree with the todo list you wrote in April, and neither agrees with the code you wrote yesterday. CNS makes that drift visible and gives you a structured ritual to resolve it.

## Quick start

**Install the Claude Code plugin** (gets you the `/cns`, `/cns-bootstrap`, `/cns-detect`, `/spar` skills):

```
/plugin marketplace add kunggaochicken/cns
/plugin install cns@cns
```

**Install the Python CLI** (gets you `cns bootstrap | reindex | detect | validate`):

```bash
pip install git+https://github.com/kunggaochicken/cns.git
# (PyPI release coming in v0.2)
```

**First-run flow:**

```bash
# In your vault:
cd path/to/your/vault
cns bootstrap              # create .cns/config.yaml with default settings

# Write your first bet (copy the template):
cp /path/to/cns/templates/bet.md.template Brain/Bets/bet_my_first.md
$EDITOR Brain/Bets/bet_my_first.md

# Regenerate the index:
cns reindex

# Run detection:
cns detect

# Resolve conflicts interactively (in Claude Code):
/spar
```

For interactive setup with a config wizard (instead of `cns bootstrap`'s defaults), use the `/cns-bootstrap` Claude Code skill.

Full walkthrough: [docs/getting-started.md](docs/getting-started.md)

## Status

v0.1 — early. Schema is versioned; breaking changes will ship migration scripts.

## License

MIT.
