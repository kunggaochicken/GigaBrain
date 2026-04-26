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
