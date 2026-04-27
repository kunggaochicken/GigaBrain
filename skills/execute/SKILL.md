---
name: execute
description: Dispatch role-scoped agents to execute active bets. Each bet's owner role does the work, stages files in Brain/Reviews/<bet-slug>/files/, and writes a distilled brief.md at the leader's altitude. Use when the user says "execute", "run my bets", "dispatch", or wants the C-suite to do the work for active bets.
---

# /execute — Dispatch role-scoped agents per bet

`/execute` reads active bets, dispatches a per-bet agent scoped to that bet's owner role's workspaces and tool allowlist, and parks each result in `Brain/Reviews/<bet-slug>/`. The leader reviews via `/spar`.

## When to use

- User says: "execute", "run my bets", "dispatch the work", "have the CTO do this"
- User wrote a bet via `/bet` and asks "now what" or "make it happen"
- User wants to refresh stale work — re-run with `--all`

## Procedure

1. **Parse arguments.** Accept these forms:
   - `/execute` — default, dispatches all active bets without a pending review
   - `/execute --all` — re-dispatches even bets with pending reviews (replaces)
   - `/execute <bet-slug>` — single bet
   - `/execute --owner <id>` — only bets owned by a role
   - `/execute --dry-run` — show plan only

2. **Run the planner.** Shell out to `cns execute --dry-run` (with whatever flags map from step 1) to print the dispatch plan. Read the output. If `cns execute init` is needed, run it first (with user confirmation).

3. **Show the plan to the user.** Print the same `[DISPATCH] / [SKIP]` table to the user verbatim, then ask:
   ```
   Dispatch N agents? [y/N]
   ```

4. **Write envelopes.** On confirmation, run `cns execute` (without `--dry-run`) to write hook configs and envelope materials to `.cns/.agent-hooks/<bet-slug>.json` and prepare `Brain/Reviews/<slug>/`.

5. **For each dispatched bet, invoke the Agent tool.** Sequential in v1. For each `[DISPATCH]` item:

   a. Read `.cns/.agent-hooks/<bet-slug>.json` to get the role config.
   b. Read the envelope materials (system_prompt, input_prompt) by re-running:
      ```
      python -c "from cns.execute import build_dispatch_queue, build_agent_envelope; import json; from pathlib import Path; from cns.config import find_vault_root, load_config; root = find_vault_root(Path.cwd()); cfg = load_config(root / '.cns/config.yaml'); plan = build_dispatch_queue(vault_root=root, cfg=cfg, bet_filter='<bet-slug>', owner_filter=None, include_pending=True); env = build_agent_envelope(item=plan[0], vault_root=root, cfg=cfg); print(json.dumps(env))"
      ```
      (Or invoke the Python directly if a `cns execute --print-envelope <bet-slug>` flag is added later.)
   c. Invoke the Agent tool with:
      - subagent_type: `general-purpose` (v1; future: a custom subagent_type per role)
      - description: `"<role-name> executing bet_<slug>"` (≤ 5 words)
      - prompt: combine the envelope's `system_prompt` + `input_prompt`. The system prompt instructs the agent to write `brief.md` per schema and stage files under the supplied review_dir.

6. **After each agent returns, validate the output.**
   - Confirm `<review_dir>/brief.md` exists.
   - Try to parse it via:
     ```
     python -c "from cns.reviews import load_brief; from pathlib import Path; load_brief(Path('<review_dir>/brief.md'))"
     ```
   - On parse failure, leave a `brief_failed: true` flag and surface the error to the user.

7. **Print final summary.** "Dispatched N bets, K produced briefs, M failed. Run `/spar` to review."

## Constraints

- NEVER edit bet files directly. `/spar` is the only writer of bet `status`.
- NEVER move staged files into workspaces. That happens at `/spar` accept time.
- ALWAYS validate every brief.md after the agent returns. A malformed brief is a real failure mode and the user needs to know.
- ALWAYS clean up `.cns/.agent-hooks/<bet-slug>.json` after the run completes (or fail loudly if it can't be cleaned).
- If a role has no workspaces (typically the leader role), skip it with a clear message — do NOT try to dispatch.

## Failure modes

- **No execution config:** the CLI exits with "Run `cns execute init`". Offer to run it.
- **Bet owner not in roles:** the planner skips with reason `unknown_owner`. Surface to user; suggest editing the bet's `owner` field.
- **Agent didn't write brief.md:** flag the bet as failed; user can re-dispatch with `/execute --all <slug>`.
- **Hook config write fails:** filesystem error; surface and abort.
