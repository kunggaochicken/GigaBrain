---
name: CNS Linear layer — persistent execution surface for agent forks
description: Add Linear as a fourth signal source and a control surface so agent-session forks (tactical and strategic) survive between dispatches and become a shared dispatch protocol for human engineers and role agents
status: active
owner: cto
horizon: this-month
confidence: medium
supersedes: null
created: 2026-04-29
last_reviewed: 2026-04-29
kill_criteria: After 3+ bets dispatched through the MVP path (steps 1–5), fork-loss continues (an unresolved out-of-scope finding is observed in a session and is not present in any spawned ticket or candidate-bet within 24h); OR the brief rollup is not load-bearing (CEO opens Linear directly more than reads briefs across 5 consecutive review cycles); OR Linear API/webhook reliability becomes a dispatch-blocking failure mode (>1 dispatch/week blocked on Linear infra) — in which case fall back to MCP-only read with no webhook-driven dispatch; OR a simpler surface (GitHub Issues alone) covers the case for solo + 1–2 contractors and the second engineer hire slips past Q3 — drop Linear entirely.
deferred_until: null
---

## The bet
CNS will gain a Linear integration layer sitting between strategic bets (vault) and ephemeral agent sessions, with three jobs: (1) persist agent forks before context dies, (2) be the surface future Gigaflow engineers already live in, (3) provide a bidirectional ticket-as-dispatch-unit protocol so humans and role agents share one channel. Identity model: 1 bet → 1 Linear Project (label `bet:<slug>`, frontmatter `linear_project: <id>`); tactical fork → Issue under that Project, owner = role id; strategic fork → candidate-bet markdown in vault (NOT a Linear issue — strategic forks need leader review at vault altitude). Source-of-truth boundaries: bet bodies and brief accept/reject stay vault-only and never get written by Linear; Issue bodies and statuses are Linear-owned with read-only sidecars under `Brain/Reviews/<bet>/tickets/`; Project existence is vault-declared and CNS-reconciled. New CLI surface: `cns ticket spawn --parent <epic> --title …` (the load-bearing piece — agents call this mid-session to make a fork durable) and `cns candidate-bet --from-ticket <id>` (V1, explicit promotion). New signal source: `cns/signals_linear.py` implementing the existing `SignalSource` protocol at `cns/signals.py:25`. Brief schema gains a `linear_tickets` rollup (open / stalled / closed counts) and a per-ticket `attempts:` block capturing failed approaches — included in MVP because it's cheap up-front and expensive to retrofit.

## Why
The fork problem is the actual pain. Across the last several agent sessions, out-of-scope findings ("noticed X while doing Y") surfaced and then died with the session because there was no durable surface to park them. Today the only options are (a) carry it in the bet body — pollutes strategic intent with tactical noise, (b) trust agent memory across dispatches — has already failed in practice, (c) GitHub Issues — works but doesn't extend to non-engineering forks (CMO finding a positioning angle mid-execution, etc.). Linear covers all three: it's general-purpose enough for any role, persistent by definition, and ticket-shaped for both human and agent consumption. The CEO altitude separation is preserved because briefs roll up Linear state — leader never opens Linear unless drilling.

The future-engineers argument is load-bearing on the Q3+ side. Once the second Gigaflow engineer joins, a shared dispatch protocol matters more than the fork-fix; if we delay until then we'll be retrofitting Linear under live multi-agent + multi-human traffic, which is the worst time to design the boundary. Better to land the boundary on the simpler N=1 case and let the next hire walk into a shaped system.

The reason for not extending GitHub Issues instead is altitude: GitHub Issues are repo-scoped, which is wrong for cross-functional forks (a CTO bet that spawns a CMO-altitude finding, for instance) and forces every non-engineering role into a code-shaped workflow. Linear is workflow-shaped and role-agnostic, which matches the recursive org-tree CLAUDE.md commits to.

The reason for shipping MVP (steps 1–5) before V1 (webhook-driven dispatch) is risk: webhooks are the most failure-prone piece and the least essential to the fork-fix. Land the persistence first, run 3+ bets through it, then add the dispatch direction once we know what actually shows up in tickets versus candidate-bets in practice. Bidirectional sync of kill_criteria to Linear cycles/milestones is explicitly out of scope at every phase — they measure different things and force-mapping creates noise (this is a known anti-pattern from prior tools, not a hypothesis).

## What would change this
- Fork-loss measured in 3+ bets is unchanged → the persistence model is wrong, not the surface (revisit: ephemeral session → durable callback shape, possibly a different primitive than ticket spawn).
- Linear ticket volume swamps brief signal (>10 tickets/bet on average within MVP) → altitude separation broke; either the role prompt is over-eager on tactical forks or the brief rollup is under-aggregating; do NOT add more wiring before fixing.
- A second engineer hire slips past Q3 AND solo + 1–2 contractors works fine on GitHub Issues → drop Linear, reduce console count, reclaim the maintenance burden.
- RemoteTrigger or another Anthropic primitive ships native cross-session persistence for agent state → Linear becomes a thin shim and the primitive collapses; this is the same risk class as the scheduling-primitive bet (`bet_cns_scheduling_primitive`) faces with RemoteTrigger.
- Linear's API model (Issues + Projects) turns out to be too rigid for the role-agnostic case (e.g., projects can't be cross-team without enterprise tier) → revisit identity model; possibly use Initiatives instead of Projects, or accept multi-Linear-team layout.

## Open threads
- Role agents as Linear users vs. labels — depends on Linear plan tier (Free/Standard caps at 3 admins, agents-as-users may not scale; labels are tier-agnostic but lose assignee semantics). Lean: labels for MVP, real pseudo-users for V1 if tier permits.
- Whether `attempts:` (failed-approach memory) ships in MVP or V1 — leaning MVP. Cheap to add to envelope contract up front (one new field in `Brief` model); expensive to retrofit because every accepted brief written without it loses that history permanently.
- Webhook hosting for V1: same box as the daily-ceo-report cron, separate process, or Cloudflare Worker / Vercel function. Lean: same box for V1 (lowest infra), migrate if reliability slips.
- Whether `linear_project` frontmatter is the right field name or whether it should be more generic (`epic_ref:` with a `kind:` discriminator) for future Jira / GitHub Projects parity. Lean: generic, even if Linear-only at MVP — frontmatter migration is painful later.
- Sidecar density: full Issue body mirrored, or just title + status + last-update? Full mirror gives offline grep; minimal mirror keeps the vault clean. Lean: minimal mirror (title + status + assignee + last-update + permalink), full body lives in Linear only.
- Drift detector behavior on Linear-only Issues (Issues with no `bet:<slug>` label): treat as drift signal in CONFLICTS.md, ignore entirely, or surface only if assigned to a `@cns-*` agent. Lean: drift signal — unlabeled work IS the signal.
- How candidate-bet promotion interacts with /spar — candidate-bets need their own walk in /spar (promote / edit / discard) or surface as a new conflict type. Lean: new conflict type, reuse /spar walk machinery.

## Linked
- evidence: []
- depends_on: []
- blocks: [[bet_cns_scheduling_primitive]]
