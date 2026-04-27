---
name: spar
description: Walk through open conflicts in CONFLICTS.md one at a time, resolving each by editing the underlying bet (confirm, edit, supersede, kill, or defer).
---

# /spar — Conflict Resolution Ritual

`/spar` is the ONLY writer to bet status fields. The detector reads bets and writes the conflicts queue; `/spar` reads the queue and writes the bets.

## Procedure

1. **Locate the vault.** Find the vault root (walk up from cwd looking for `.cns/config.yaml`). Read the config.

2. **Load the queue.** Read `<vault>/<conflicts_file>`. Parse each conflict using the format:
   ```
   ### C-YYYY-MM-DD-<slug> (N days open)
   - **Bet:** [[bet_<file>]]
   - **Trigger:** ...
   - **Detector note:** ...
   ```

3. **Filter deferred.** For each conflict, read the linked bet file. Skip conflicts where the bet's `deferred_until` field is set and is in the future.

4. **Sort.** Across all role sections, sort remaining conflicts oldest-first by `first_detected` (parsed from the conflict ID).

5. **If empty queue:** print "No open conflicts. Nothing to spar." and exit.

6. **Walk one at a time.** For each conflict:

   a. **Display the conflict.** Show: bet name, owner, current `## The bet`, current `## Why`, current `kill_criteria`, the trigger, the detector note, and `last_reviewed`.

   b. **Read linked evidence.** Parse the bet's `## Linked` section. For each `evidence: [[path]]` entry, read that file and show the user a one-paragraph summary so they can spar with full context.

   c. **Ask one of (multiple choice):**

      ```
      How do you want to resolve this?
      [c] Confirm — bet still holds, mark reviewed
      [e] Edit  — change kill_criteria / The bet / Why, then mark reviewed
      [s] Supersede — kill this bet, create a replacement with `supersedes:` set
      [k] Kill — bet is dead, no replacement
      [d] Defer — set `deferred_until: <date>` and skip for now
      [q] Quit — end the sparring session
      ```

   d. **Apply the resolution.** For each choice:

      - **[c] Confirm:** Edit the bet file: set `last_reviewed: <today>`. Remove the conflict from `<conflicts_file>`.
      - **[e] Edit:** Ask the user what to change. Apply edits to the bet file. Set `last_reviewed: <today>`. If the user filled in a previously-unspecified `kill_criteria`, that's the most common edit. Remove the conflict.
      - **[s] Supersede:** Ask "what's the new bet?" Append a `## Tombstone` section to the current bet (Final call: <text>; Why it died: <text>; Replaced by: [[bet_<new>]]; Date: <today>). Set `status: superseded`. Create the new bet file with `supersedes: <old-filename>` and the rest of the schema filled. Run `cns reindex`. Remove the conflict.
      - **[k] Kill:** Append `## Tombstone` (Replaced by: null). Set `status: killed`. Run `cns reindex`. Remove the conflict.
      - **[d] Defer:** Ask "until when?" (default: 7 days). Set `deferred_until: <date>` on the bet. Remove the conflict from the queue. (It will be re-detected after the date passes if still relevant.)
      - **[q] Quit:** Print "Ended at conflict X of Y. <remaining> conflicts left." and exit.

   e. **After each resolution**, ask "Next conflict?" (default yes; user can quit at any point).

7. **Final commit prompt.** When the queue is empty or the user quits, ask: "I've made N edits to bet files and updated CONFLICTS.md. Want me to commit these as `chore(brain): spar session YYYY-MM-DD`?" Wait for explicit yes.

## Constraints

- NEVER edit a bet's `status` field unless the user chose [s] or [k].
- NEVER remove a conflict from the queue unless the resolution succeeded.
- ALWAYS update `last_reviewed` when resolving any conflict via [c] or [e] (this is the staleness clock reset).
- ALWAYS run `cns reindex` after any change to a bet's `status` field.
- If parsing a bet file fails mid-session, stop the session, surface the error, and do not delete the conflict from the queue.

---

## Phase 2: Reviews (added by /execute)

After the conflicts walk completes (or if there were no conflicts), enter Phase 2 to walk pending reviews from `Brain/Reviews/<slug>/`.

### Procedure

1. **Locate the reviews directory.** Read the loaded config; if `cfg.execution` is None, skip Phase 2 entirely. Otherwise, walk `<vault>/<cfg.execution.reviews_dir>`.

2. **Load pending reviews.** Run:
   ```bash
   cns reviews list --vault <vault>
   ```
   Read the output. If empty, print "No pending reviews. /spar complete." and exit.

3. **Sort.** Pending reviews come back already sorted oldest-first by `agent_run_id`.

4. **For each review:**

   a. **Re-run detection against the staged files.** Build a snapshot of "active or historical bets that share distinctive words with the staged files' content." Compare to the brief's `related_bets_at_write` snapshot; the *delta* is what's new since the agent ran. Highlight new entries.

   b. **Display:**
      - Bet name + owner + the bet's `## The bet` and `## Why` (read the bet file)
      - The brief's `## TL;DR for the CEO`
      - The brief's `## Decisions I need from you`
      - Related bets — combined snapshot + delta, with NEW items marked
      - Verification frontmatter (any failed `cmd` is a red flag — surface it)
      - `files_touched` — paths only, not diffs (unless the user picks `[v]`)

   c. **Ask:**
      ```
      How do you want to resolve this review?
      [a] Accept       — promote files into workspaces, archive the review
      [r] Reject       — archive the review, no workspace changes
      [e] Edit-and-rerun — append reviewer notes, re-dispatch via /execute
      [d] Defer        — set deferred_until on the bet, keep review pending
      [v] View diff    — show files/ contents and re-prompt
      [q] Quit
      ```

   d. **If [a] Accept:**

      i. If `brief.proposed_closure` is True, ask "Mark bet as `done`?" [y/N], default y.

      ii. If any contradicting active bets are present in the snapshot or delta, ask:
         ```
         This work supersedes [bet_X, bet_Y] — handle them?
         [s] Supersede each  (existing /spar supersede flow per bet)
         [k] Kill each
         [n] Leave them
         ```

      iii. Run `cns reviews accept <slug>`. This promotes staged files into workspaces and archives the review.

      iv. If user chose to mark done: edit the bet file, set `status: done` and `last_reviewed: <today>`. Run `cns reindex`.

      v. If user chose supersede or kill on contradicted bets: use the existing `/spar` supersede/kill flow on each.

   e. **If [r] Reject:**
      Run `cns reviews reject <slug>`. Bet is unchanged.

   f. **If [e] Edit-and-rerun:**
      Open the brief in the user's editor (or accept inline text). Append the user's notes as a `## Reviewer notes` section to `brief.md`. Then run `cns execute --bet <slug> --all` to re-dispatch (the `--all` flag forces replacement of the existing pending review).

   g. **If [d] Defer:**
      Ask "Until when?" (default 7 days from today). Set `deferred_until: <date>` on the bet file. Leave the review pending.

   h. **If [v] View diff:**
      For each file in `brief.files_touched`, print the staged file path and the workspace destination, then `cat` the staged file (or `diff` it against the workspace if the destination exists). Re-show the resolution menu.

   i. **If [q] Quit:**
      Print "Ended at review X of Y. <remaining> reviews left." and exit.

5. **Final commit prompt** (extends existing pattern):
   "I made N edits to bet files / accepted M reviews / rejected K. Want me to commit these as `chore(brain): spar session YYYY-MM-DD`?"

### Constraints

- NEVER move staged files manually — always use `cns reviews accept` so the brief is updated and archival happens atomically.
- NEVER mark a bet `done` unless the user explicitly chose that option.
- NEVER edit `brief.md` to flip its `status` field manually — the `cns reviews accept|reject` commands handle this.
- ALWAYS show contradicting bets to the user before they accept; the snapshot+delta is the load-bearing context for the decision.
