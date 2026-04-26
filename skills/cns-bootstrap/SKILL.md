---
name: cns-bootstrap
description: Initialize CNS in a new vault. Two modes — `--blank` (empty config wizard) and `--from-existing` (extract bets from existing strategic docs).
---

# CNS Bootstrap

Initialize a Central Nervous System (CNS) installation in the current vault.

## Modes

**`--blank`** — Set up an empty CNS structure with a config wizard. Use this for a brand-new vault or when starting fresh.

**`--from-existing <paths...>`** — Extract draft bets from existing strategic docs. Use this when migrating an existing vault into CNS.

## --blank mode

When invoked with `--blank` or no argument:

1. **Detect vault root.** If the user is in a directory whose ancestors do not contain `.cns/config.yaml`, ask: "Should I treat the current directory as the vault root, or specify a different path?"

2. **Run the config wizard.** Ask the user (one question at a time):

   a. **Brain folder name?** Default: `Brain`. Accept any vault-relative path.

   b. **Role roster?** Show the two presets:
      - `solo-founder`: ceo, cto, cso (chief scientist), cmo, cpo, clo, cfo
      - `engineering-lead`: engineer, manager, designer, pm
      - `custom`: ask for a list

   c. **Horizon thresholds?** Default: `this-week=7, this-month=30, this-quarter=90, strategic=180`. Ask if user wants to override any.

   d. **Signal sources?** For each:
      - "Add a vault directory whose .md edits should count as signal? (e.g., `Daily/`, `Research/`, `Marketing/`. Empty to skip.)"
      - "Add a git repo to scan for commits? (path relative to vault root. Empty to skip.)"
      - "Add a GitHub repo to scan for merged PRs? (`owner/repo` format. Empty to skip.)"

   e. **Daily report integration?** "Do you have a daily-note flow at <vault>/Daily/YYYY-MM-DD.md that CNS should append conflict summaries to?" (yes/no)

3. **Write the config.** Create `<vault>/.cns/config.yaml` from the answers.

4. **Create directories.** Make `<vault>/<brain>/Bets/` and an empty `<vault>/<brain>/CONFLICTS.md` (just the `# Open Conflicts` header).

5. **Validate.** Run `cns validate --vault <vault>`. If it fails, show the user the error and offer to re-run the wizard.

6. **Confirm.** Show the user where files were written and suggest the next step:
   > "CNS bootstrapped at `<vault>`. Next steps:
   > 1. Write your first bet by copying `templates/bet.md.template` to `<bets_dir>/bet_<slug>.md`
   > 2. Run `cns reindex` to regenerate the index
   > 3. Run `cns detect` to see initial conflicts (will surface 'unspecified — needs sparring' on any bet without explicit kill_criteria)"

## --from-existing mode

When invoked with `--from-existing <path1> <path2> ...` (paths relative to vault root):

1. **Pre-flight.** Verify `.cns/config.yaml` exists. If not, run `--blank` first.

2. **Read the source material.** Read every `.md` file under each provided path. Typical inputs:
   - `Strategy/*.md`
   - `Research/**/*.md` (especially `REPORT-FOR-CEO.md` files)
   - `memory/*.md`
   - `Marketing/*.md`

3. **Extraction prompt — give yourself this brief:**

   > Extract every distinct strategic bet, decision, or active commitment visible in the source documents. A bet is a load-bearing call that:
   > - has a stated direction ("we will do X")
   > - has reasoning behind it (even if implicit)
   > - could be wrong (i.e., something could change to make it stop being true)
   >
   > For each bet, draft a `bet_<slug>.md` file using the schema in `templates/bet.md.template`. Fill every field except `kill_criteria` — leave that as `"unspecified — needs sparring"` unless the source material explicitly states what would kill the bet.
   >
   > **Critical**: where source documents disagree (e.g., one doc says fundraising Q1 2027 and another says Q3/Q4 2026), produce **two contradictory draft bets**, both with `status: active`, both with the conflicting `## The bet` text. The detector will surface these as cross-bet contradictions; the user resolves in the first sparring session.
   >
   > Aim for 10–20 bets total. Cluster by `owner` role using the roster in `.cns/config.yaml`. Use your judgment for owner assignment based on the bet's content.

4. **Write the draft files.** Place all draft `bet_<slug>.md` files in `<vault>/<bets_dir>/`. Do NOT overwrite any existing bet files — if a slug collides, append `_v2`, `_v3`, etc.

5. **Generate the index.** Run `cns reindex --vault <vault>` to produce `BETS.md`.

6. **Print the review prompt.**
   > "I drafted N bets in `<vault>/<bets_dir>/`. Please review:
   > 1. Open `<vault>/<bets_dir>/BETS.md` to see the full list.
   > 2. Read each draft bet — accept, edit, or reject.
   > 3. For contradictory pairs (I marked them with the same root slug + `_v2`), pick one (or merge), tombstone the loser via `/spar`.
   > 4. Fill in `kill_criteria` where the answer is obvious. Leave `'unspecified — needs sparring'` where it isn't.
   >
   > When you're done, run `cns detect` to start the regular conflict-detection cycle. Optionally, add a 'decomposed into Brain/Bets/' header to the source documents you extracted from (use `--add-decomposed-headers` to do this automatically)."

7. **`--add-decomposed-headers` flag.** If the user passes this flag, prepend the following header to each source `.md` file used in extraction (idempotent — check if the marker already exists before inserting):

   ```markdown
   <!-- cns-decomposed -->
   > **Decomposed into [[<bets_index_path>]] on YYYY-MM-DD.** This document is preserved
   > for historical context but is no longer the source of truth for active bets.
   > See `<bets_dir>/` for current strategic state.

   ```

   Use the sentinel comment `<!-- cns-decomposed -->` to detect prior insertion.
