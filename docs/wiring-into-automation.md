# Wiring CNS into existing automation

CNS's detector (`cns detect`) is a one-shot, idempotent CLI command. Wire it into whatever cron, post-commit hook, or daily-report flow you already have.

## Daily report cron (e.g., a "Daily CEO Update" script)

Add a Step 6.5 between report-write and commit:

```bash
# After writing today's daily note:
cns detect --vault /path/to/vault

# CNS updated:
#   <vault>/Brain/CONFLICTS.md         (always)
#   <vault>/Daily/<today>.md           (if config has automation.daily_report.daily_note_dir)
# Commit those alongside the daily note.
git -C /path/to/vault add Brain/CONFLICTS.md Daily/$(date +%F).md
git -C /path/to/vault commit -m "cns: detection $(date +%F)" || true
git -C /path/to/vault push || true
```

To get the "Open conflicts: N (oldest M days)" line injected into your daily note's TL;DR, set in `.cns/config.yaml`:

```yaml
automation:
  daily_report:
    integration: optional
    inject_tldr_line: true
    daily_note_dir: Daily
```

The injection is idempotent — running `cns detect` multiple times on the same day inserts the line once.

## Pre-commit hook

If you want every commit to a bet file to trigger reindex:

```bash
# .git/hooks/pre-commit
#!/bin/bash
if git diff --cached --name-only | grep -q "^Brain/Bets/bet_"; then
  cns reindex
  git add Brain/Bets/BETS.md
fi
```

## Post-merge hook (e.g., after pulling teammate edits to bets)

```bash
# .git/hooks/post-merge
#!/bin/bash
cns reindex
cns detect
```
