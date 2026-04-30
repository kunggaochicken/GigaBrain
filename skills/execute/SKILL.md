---
name: execute
description: Dispatch role-scoped agents to execute active bets. Each bet's owner role does the work, stages files in Brain/Reviews/<bet-slug>/files/, and writes a distilled brief.md at the leader's altitude. Use when the user says "execute", "run my bets", "dispatch", or wants the C-suite to do the work for active bets.
---

# /execute — Dispatch role-scoped agents per bet

`/execute` reads active bets, dispatches a per-bet agent scoped to that bet's owner role's workspaces and tool allowlist, and parks each result in `Brain/Reviews/<bet-slug>/`. The leader reviews via `/spar`.

> **v0.3 — path/web/bash scoping is hook-enforced when the user opts in.** A
> Claude Code PreToolUse hook (`cns-hook-pretooluse`) reads
> `.cns/.agent-hooks/<bet-slug>.json` and denies Edit/Write outside the
> staging dir, WebFetch outside the role's `web_allowlist`, and Bash
> commands outside `bash_allowlist`. The hook is **opt-in**: install the
> snippet from `templates/claude-settings.hook.json.template` per
> [`docs/installing-hook-executor.md`](../../docs/installing-hook-executor.md).
> When the hook is not installed, scoping falls back to prompt-enforcement
> (the dispatched agent's system prompt still tells it to stay in scope).
> Closes [#30](https://github.com/kunggaochicken/GigaBrain/issues/30) /
> tracks [#20](https://github.com/kunggaochicken/GigaBrain/issues/20).

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

4. **Write envelopes.** On confirmation, run `cns execute` (without `--dry-run`) to drop a hook descriptor at `.cns/.agent-hooks/<bet-slug>.json` and prepare `Brain/Reviews/<slug>/`. When the v0.3 PreToolUse hook is installed (`cns-hook-pretooluse`, see `docs/installing-hook-executor.md`), this descriptor is the source of truth for path/web/bash scoping. Scoping is also still injected into the agent's system prompt in step 5 as a belt-and-suspenders defense.

5. **For each dispatched bet, invoke the Agent tool.** Sequential in v1. For each `[DISPATCH]` item:

   a. Read `.cns/.agent-hooks/<bet-slug>.json` to get the role config.
   a'. **Mark the bet active for the hook executor:** run `cns hook-active set <bet-slug>`. The PreToolUse hook reads
       `<vault>/.cns/.agent-hooks/.active` to know which descriptor to enforce against. (Or set `CNS_ACTIVE_BET=<slug>` and
       `CNS_VAULT_ROOT=<vault>` in the dispatcher's env if you have a way to propagate them to the Agent subprocess.) When the
       agent returns, run `cns hook-active clear` so the hook returns to open mode.
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

   - **Capture cost.** The Agent tool's result carries token usage (`input_tokens`, `output_tokens`, `cache_read_input_tokens`, `cache_creation_input_tokens`, plus the `model` id). Compute the dollar cost via `cns.pricing.cost_usd(model, usage)` and patch a `cost:` block into the brief's frontmatter:
     ```python
     from cns.pricing import cost_usd, canonical_model
     from cns.reviews import CostRecord, load_brief, write_brief
     b = load_brief(p)
     b.cost = CostRecord(
         model=canonical_model(model),
         input_tokens=usage["input_tokens"],
         output_tokens=usage["output_tokens"],
         cache_read_tokens=usage.get("cache_read_input_tokens", 0),
         cache_write_tokens=usage.get("cache_creation_input_tokens", 0),
         usd=cost_usd(model, usage),
     )
     write_brief(p, b)
     ```

7. **Print final summary.** Include the per-bet cost and a session total: e.g. `Dispatched N bets ($X.XX total), K produced briefs, M failed.` Run `/spar` to review.

## Constraints

- NEVER edit bet files directly. `/spar` is the only writer of bet `status`.
- NEVER move staged files into workspaces. That happens at `/spar` accept time.
- ALWAYS validate every brief.md after the agent returns. A malformed brief is a real failure mode and the user needs to know.
- ALWAYS clean up `.cns/.agent-hooks/<bet-slug>.json` after the run completes (or fail loudly if it can't be cleaned). Also run `cns hook-active clear` to remove the active-bet sentinel — leaving it set will cause the v0.3 PreToolUse hook to keep enforcing against a stale descriptor in subsequent Claude Code sessions.
- If a role has no workspaces (typically the leader role), skip it with a clear message — do NOT try to dispatch.

## Web tools (`tools.web`, `tools.web_allowlist`)

Roles that need to research, pull docs, or read competitor pages can opt in to
WebFetch:

```yaml
tools:
  web: true
  web_allowlist:
    - "docs.example.com"
    - "*.example.com"
```

Rules:

- `tools.web: false` (the default) means no `WebFetch` / `WebSearch`. Per-role,
  zero exceptions.
- `tools.web: true` requires `tools.web_allowlist` to be set; entries are domain
  globs matched against the URL host via `fnmatch` (so `*.example.com` matches
  any subdomain).
- The schema also forbids the inverse: an allowlist with `web: false` is a
  config error so YAML reviews are unambiguous.
- The CMO template ships with `web: true` because the CMO-agent in particular
  needs to fetch reference material; every other template defaults to `web: false`.

**Source archival (single console).** Every successful WebFetch must be
archived under `Brain/Reviews/<bet-slug>/sources/<sha256-prefix>.md` with
frontmatter `url: <url>` and `fetched_at: <iso8601>`. This is how the leader
audits sources without leaving the vault. The dispatcher injects these
instructions into the agent's system prompt; the agent is responsible for
writing the file.

**v0.3 enforcement.** When the PreToolUse hook is installed (see
`docs/installing-hook-executor.md`), `WebFetch` calls go through
`cns-hook-pretooluse`, which denies any URL whose host is not in
`tools.web_allowlist` and any call when `tools.web: false`. Without the
hook, the agent's system prompt is still the only constraint — install
the hook for actual enforcement. `WebSearch` is gated coarsely by the
boolean `tools.web` flag (no per-host check, since search has no URL
to inspect at request time).

## Failure modes

- **No execution config:** the CLI exits with "Run `cns execute init`". Offer to run it.
- **Bet owner not in roles:** the planner skips with reason `unknown_owner`. Surface to user; suggest editing the bet's `owner` field.
- **Agent didn't write brief.md:** flag the bet as failed; user can re-dispatch with `/execute --all <slug>`.
- **Hook config write fails:** filesystem error; surface and abort.

## Recursive sub-delegation (v0.4+, issue #9)

A leader-agent that's mid-run (e.g. the CTO running this bet) can spawn its
own subordinates inline by shelling out to `cns execute --from-leader <self>
--bet <sub-bet-slug>`. This is how the org tree extends recursively: a CTO
that needs to delegate a piece of work to an engineer-agent can do so
without bouncing back to the CEO.

> **Requires `execution.reviews_dir_per_leader: true`** (issue #33). Sub-dispatch
> routes the sub-agent's brief into `<reviews_dir>/<parent_leader_id>/<sub-slug>/`,
> which is only consistent when the rest of the vault uses the per-leader layout.
> Calling `cns execute --from-leader …` against a vault with the flag off exits
> non-zero and tells the user to set `execution.reviews_dir_per_leader: true` in
> `.cns/config.yaml` and run `cns vault migrate-reviews --apply`. Flip the flag
> once when you start using recursion, then leave it on.

### Contract

A leader-agent that wants to sub-delegate:

1. **Authors the sub-bet first.** The leader writes
   `Brain/Bets/bet_<sub-slug>.md` with the same frontmatter shape `/bet`
   uses. The bet's `owner` MUST be a role that reports DIRECTLY to the
   calling leader; otherwise dispatch refuses with `role_not_subordinate`.
2. **Calls the dispatcher.** The leader runs:
   ```
   cns execute --from-leader <self-id> --bet <sub-slug> \
       --chain '<chain-json>' \
       --session-spend '<usd-decimal-string>'
   ```
   - `--chain` is a JSON list of `[role_id, bet_slug]` pairs starting at
     the top-level leader and ending at the calling leader. The envelope
     a leader-agent receives carries this chain in `envelope["chain"]` —
     pass it through unchanged.
   - `--session-spend` is the running USD total ancestors have already
     spent, so the global `per_session_usd_max` cap can't be circumvented
     by deep recursion. Pass through `envelope["new_session_spend"]` from
     the previous hop.
3. **Reads the sub-agent's envelope.** On success, the CLI prints
   `[depth=N] [DISPATCH]` plus the review_dir / hook_config_path. The
   leader hands those off to the Agent tool exactly like the top-level
   `/execute` does.
4. **Reviews the sub-brief.** The sub-agent's brief lands in the leader's
   per-leader subdir: `Brain/Reviews/<self-id>/<sub-slug>/brief.md`. The
   leader reads it, decides whether to escalate, and (if so) writes a
   distilled summary into ITS OWN leader's queue. There is NO automatic
   bubble-up — distillation is an explicit choice (see CLAUDE.md's vision
   on the org-tree model).

### Refusal modes

The CLI exits non-zero (and the leader-agent's shell-out fails) on any of:

- `reviews_dir_per_leader` is false — see the requirement note above. The
  CLI tells the user which knob to flip and to run `cns vault migrate-reviews`.
- `role_not_subordinate` — sub-bet owner does not directly report to the
  calling leader. Likely a typo'd `owner` field or the wrong leader id.
- `depth_limit` — the dispatch chain would exceed
  `execution.max_dispatch_depth` (default 3, configurable). The CEO ->
  CTO -> VP-Eng -> engineer canonical chain is depth 3.
- `cycle_detected` — the sub-bet's owner already appears in the chain.
  Same role twice = cycle. Same bet slug repeating across different roles
  is allowed (legitimate escalation pattern).
- The standard budget refusals (`budget_per_run`, `budget_per_session`,
  `budget_per_role_daily`) all apply: per_session is global across the
  recursion (counts the threaded session-spend), per_role_daily applies
  to the sub-role.

### When NOT to sub-delegate

If the work fits inside the calling leader's altitude — small
implementation tweaks, a single file edit, a quick verification — just
do it inline. Sub-delegation has overhead: another agent boot, another
brief to read, more cost. Reach for it when the work is genuinely
in a subordinate's domain (e.g. a CTO asking an engineer to dive into
specific source files).
