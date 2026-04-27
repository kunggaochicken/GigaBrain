---
name: bet
description: Create a new bet through guided questions. Walks the user through name, owner, horizon, confidence, and kill_criteria, then writes the bet file and re-indexes. Use when the user says "create a bet", "new bet", "I want to bet on X", or describes a strategic decision they want to track.
---

# /bet — Create a new strategic bet

`/bet` is the conversational front door for adding bets. It enforces the most-skipped field (`kill_criteria`) by refusing to write the file without it.

## When to use

- User says: "new bet", "create a bet", "add a bet", "I want to bet on X"
- User describes a strategic decision they want CNS to track
- A `/spar` supersede flow needs to create a replacement bet (the supersede path calls into the same primitive; that's not this skill, but the same primitive `cns.bet.create_bet`)

## Procedure

1. **Locate the vault.** Walk up for `.cns/config.yaml`. Read the config to get the role list and horizon keys.

2. **Ask one question at a time:**

   a. **"What's the bet? (1-2 sentences)"** — capture name and description. The first sentence becomes `name`, the second (or first if only one) becomes `description`.

   b. **"Whose call is this?"** — multiple choice from `cfg.roles`. Use the role's `name` as the display label, the `id` as the value.

   c. **"Horizon?"** — multiple choice: `this-week`, `this-month`, `this-quarter`, `strategic`.

   d. **"Confidence?"** — multiple choice: `low`, `medium`, `high`.

   e. **"What would change this?"** — free-form. This is the `kill_criteria`. **Do not accept skip / blank / "TBD" / "unspecified".** If the user pushes back, explain that without kill criteria the bet will get flagged in every conflict run as needing sparring; ask them to give even a one-line answer.

   f. **"Does this supersede an existing bet?"** — `[n]` (default) or pick from a list of active bets.

3. **Derive the slug.** Lowercase, snake_case the name. The CLI primitive handles collision dedupe (`_2`, `_3`, …).

4. **Write the bet.** Use the Python primitive directly:
   ```bash
   python -c "
   from datetime import date
   from pathlib import Path
   from cns.bet import create_bet
   from cns.config import find_vault_root, load_config
   root = find_vault_root(Path.cwd())
   cfg = load_config(root / '.cns/config.yaml')
   path = create_bet(
       bets_dir=root / cfg.brain.bets_dir,
       name='<name>', description='<description>',
       owner='<role-id>', horizon='<horizon>', confidence='<conf>',
       kill_criteria='<kill_criteria>',
       supersedes=<None or 'bet_<old>.md'>,
       today=date.today(),
   )
   print(path)
   "
   ```

5. **Re-index.** Run `cns reindex`. Show the user the path that was written.

6. **Suggest next step.** Print: "Wrote `bet_<slug>.md`. Run `/execute --bet <slug>` to dispatch, or write more bets first."

## Constraints

- NEVER write the bet file without a non-empty `kill_criteria`. If the user truly cannot articulate one, refuse and suggest they think through it; do not fall back to the legacy "unspecified — needs sparring" sentinel via this skill.
- NEVER guess the owner. If the user's intent is ambiguous, ask.
- ALWAYS confirm the slug before writing if it differs significantly from what the user might expect (e.g., if the name has special characters).
- If `supersedes` is set, surface the old bet's `## The bet` and `## Why` to the user before writing — they should see what they're replacing.
