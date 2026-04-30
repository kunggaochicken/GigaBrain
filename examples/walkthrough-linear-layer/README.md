# Walkthrough: building Gigaflow's Linear layer with GigaBrain

This is a self-referential demo. The thing GigaBrain is helping you build, in this walkthrough, is *a layer that GigaBrain itself doesn't yet have* — Linear integration. The conversation that produced this walkthrough is the worked example. You play the CEO. GigaBrain plays the org.

If you read only one thing: the point isn't that Linear gets built at the end. The point is that **you, the leader, only ever touch the vault** — write a bet, read a brief, walk conflicts in `/spar`. Everything else (Linear, code, PRs, agent sessions) happens below your altitude and gets distilled back up.

## The meta-mapping

Take the conversation that led here and pin each piece to a GigaBrain artifact. This is exactly the translation you'd do for any Gigaflow strategic decision.

| Conversation moment | GigaBrain artifact | Where it lives |
|---|---|---|
| "I'm overwhelmed by my stack" (the prompt) | A leader's note. Not a bet yet — too vague. | Obsidian daily note, free text |
| The architecture sketch and three options (A/B/C) | Brainstorming output. Pre-bet. | Obsidian scratch page (or your daily note) |
| "Forks are the real problem; Linear is the right tool" (the call) | The **bet** — strategic intent + kill criteria | `Brain/Bets/bet_cns_linear_layer_v1.md` |
| MVP steps 1–5 in the design proposal | **Tickets** under the bet's Linear Project | Linear (Issue per step), once the layer ships |
| "attempts-as-memory" insight that emerged mid-design | A **strategic fork** → candidate-bet | `Brain/Bets/_candidates/attempts_as_memory.md` (today: a sibling note) |
| "Build steps 1–3 only this week" | **Dispatch envelope** for `/execute` | Computed by `cns/execute.py` from the bet |
| The eventual pass/fail call after a week of running | **Brief** + accept/reject in `/spar` | `Brain/Reviews/<bet>/brief.md`, then archived |

The bet artifact for this walkthrough is in [`bet_cns_linear_layer_v1.md`](./bet_cns_linear_layer_v1.md). Drop it in your vault under `Brain/Bets/` and you have a real, runnable starting point.

## How you (the CEO) actually use Obsidian

Three modes, in this order of frequency:

1. **Read briefs** — `Brain/Reviews/<bet>/brief.md` is where distilled status lands. You skim. If the brief looks fine, you accept. You do not open repos, Linear, or `cns/` source. The brief is the contract.
2. **Walk conflicts** — when the detector flags drift (a vault edit contradicts an active bet, a PR ships work no bet covers, etc.), it lands in `Brain/CONFLICTS.md`. You run `/spar`, walk them one at a time, edit the underlying bet or kill it.
3. **Write or amend bets** — only when strategic intent itself changes. If a brief surfaces a strategic fork, the candidate-bet is already written for you; you just promote, edit, or reject.

Ingesting information *into* the system happens in two places only: the bet body when you change strategy, and `/spar` decisions when you confirm/edit/kill/supersede in response to drift. Everything else is downstream automation.

## Run the loop end-to-end

The steps below are what *you* do, with my prompts at each gate. The bet exists; the rest is muscle memory.

> **Honest caveat.** Step 6 (the Linear control surface) is the layer this bet is *building*. So in this walkthrough, the Linear part is partially mocked — you'll see the agent log a `cns ticket spawn` call against a stub, not a live Linear Project. Steps 1–5 are real today.

### Step 1 — Bootstrap (one-time, skip if already done)

```bash
cd /path/to/your/Brain   # your Obsidian vault root
cns bootstrap --preset solo-founder
git init && git add .cns Brain && git commit -m "cns: bootstrap"
```

You should now have `.cns/config.yaml`, `Brain/Bets/`, and an empty `Brain/CONFLICTS.md`.

### Step 2 — Drop in the bet

```bash
cp examples/walkthrough-linear-layer/bet_cns_linear_layer_v1.md \
   /path/to/your/Brain/Bets/bet_cns_linear_layer_v1.md
cns reindex
```

Open `Brain/Bets/BETS.md` in Obsidian. The new bet should show up under `cto`. **This is where you'd normally pause and edit the kill criteria** — try it. The current criteria are mine; yours might differ.

### Step 3 — Run detection cold

```bash
cns detect
```

You'll likely get one or two flags — typically that this bet has no linked evidence yet, or that `last_reviewed` is unchanged since creation. Open `Brain/CONFLICTS.md` and read what showed up. Don't fix anything yet.

### Step 4 — Spar the conflicts

In Claude Code:

```
/spar
```

Walk each flagged item. For most you'll choose `[c] Confirm` — you stand by the bet as written. For any that prompt a real edit, do it. This is the leader's altitude: confirm, edit, supersede, kill, or defer.

### Step 5 — Dispatch the bet

```
/execute bet_cns_linear_layer_v1
```

This is where a CTO role agent picks up the bet, decomposes it, and starts work. In a built-out Linear layer, this would also create the Linear Project + seed Issue. Today, the agent works against the repo and writes back a `Brain/Reviews/bet_linear_layer_v1/brief.md`. Open it. **Read only the brief.** Resist opening any code the agent touched. If the brief is vague, that's the signal — the agent prompt is wrong, not the bet.

### Step 6 — Watch a fork get captured (the moment this bet exists for)

While the agent runs, it will hit something out-of-scope — for instance, "the existing `SignalSource` protocol doesn't expose pagination, this matters for Linear webhook backfill." Two outcomes are possible:

- **Tactical fork** — the agent calls `cns ticket spawn --parent <epic> --title "Add pagination to SignalSource"`. In the partially-mocked walkthrough, this writes a stub entry to `Brain/Reviews/bet_cns_linear_layer_v1/tickets/` instead of hitting Linear. Either way, the fork is durable. The agent returns to the original work.
- **Strategic fork** — the agent surfaces a `Brain/Bets/_candidates/attempts_as_memory.md` candidate-bet (this one really happened mid-design). It's queued for your review, not executed. You decide later whether to promote or discard.

This is the entire point of the layer. **The fork survives the session.**

### Step 7 — Accept or reject

Back in `/spar` (or directly in the brief), accept the brief if the work matches the bet, reject if it drifted. Acceptance archives the brief and updates the bet's `last_reviewed`. Rejection routes back as a conflict: "agent shipped X, bet says Y" — and you walk it next round.

## What "good" looks like after one cycle

- You read 1 brief (~200 words) for ~30 seconds.
- You spent 0 minutes in Linear.
- You spent 0 minutes reading code.
- 1–3 forks got captured durably that would have died in a session before.
- `Brain/CONFLICTS.md` has 0–2 entries, each resolvable in a single `/spar` decision.

If any of those are off — especially if you found yourself opening Linear or the repo to figure out what happened — the brief contract is broken. That's a higher-priority signal than the bet itself.

## What this walkthrough is *not*

- Not a how-to for the Linear layer's implementation. The bet specifies *what* to build; the agent decomposes *how*.
- Not a substitute for `docs/getting-started.md`. That doc covers the bare CNS install. This one covers the leader's daily loop, end-to-end, on a bet that builds GigaBrain itself.
- Not exhaustive on edge cases (multi-leader review queues, recursive sub-dispatch, role tool allowlists). Those are real and live elsewhere — they don't change the loop you just ran.
