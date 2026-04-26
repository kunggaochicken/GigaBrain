---
name: cns-detect
description: Run CNS conflict detection. Wraps `cns detect` CLI with a friendly summary for interactive use. For unattended automation, call the CLI directly.
---

# /cns-detect — Run conflict detection

Wraps the `cns detect` CLI for interactive use. For cron / unattended runs, use the CLI directly:

```bash
cns detect --vault <vault-root>
```

## Procedure (interactive use)

1. **Find the vault root.** Walk up from cwd. If no `.cns/config.yaml`, ask the user where their vault is.

2. **Run the CLI.**
   ```bash
   cns detect --vault <vault>
   ```

3. **Parse the output.** The CLI prints `Wrote <path> (N conflicts)`.

4. **If N > 0:** Read the conflicts file and summarize:
   - Total open conflicts, broken down by owner role
   - Oldest conflict and its age
   - Any conflicts flagged as "needs sparring" (kill_criteria unspecified)
   - Suggest: "Run `/spar` to walk through these one at a time."

5. **If N == 0:** Print "No conflicts detected. All active bets are up-to-date and consistent."

## Wiring into existing automation

If the user has a daily-report cron, recommend wiring `cns detect` in as a post-report step:

```bash
# In the cron script, after writing the daily report:
cns detect --vault <vault-root>
git add <vault>/Brain/CONFLICTS.md <vault>/Daily/<today>.md
git commit -m "cns: detection $(date +%F)"
git push
```

The detector is idempotent — running it multiple times in a day is safe (existing conflict IDs are preserved with their `first_detected` date).
