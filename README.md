# CNS — Central Nervous System

Atomized strategic bets with automated conflict detection for markdown vaults.

## What it does

CNS turns scattered strategy docs (planning notes, todos, daily journals, memory files) into one-bet-per-file atoms with explicit kill criteria. A nightly detector compares your active bets against new vault edits, git commits, and GitHub PRs — and surfaces anything that contradicts an active bet. A `/spar` skill walks you through resolving conflicts one at a time.

## Why

Strategic state drifts. The strategy doc you wrote in March doesn't agree with the todo list you wrote in April, and neither agrees with the code you wrote yesterday. CNS makes that drift visible and gives you a structured ritual to resolve it.

## Quick start

```bash
pip install cns

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

For interactive setup with a config wizard, use the `/cns-bootstrap` Claude Code skill instead.

Full walkthrough: [docs/getting-started.md](docs/getting-started.md)

## Status

v0.1 — early. Schema is versioned; breaking changes will ship migration scripts.

## License

MIT.
