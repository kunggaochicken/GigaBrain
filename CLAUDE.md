# GigaBrain CNS — project conventions

## Vision: GigaBrain is a delegation console for a leader

GigaBrain is built for the **leader of any team** — most centrally a CEO, but the same shape applies to a team manager, tech lead, or anyone who delegates strategic work to people (or agents) who can mostly execute independently.

**The mental model is a company org structure:**

- The leader (e.g. CEO) issues **vision, strategic bets, and positioning decisions**. They do not work on minute details.
- Subordinate roles (e.g. CTO, CMO, CPO, Chief Scientist) **operate mostly independently** within their domain. They have closer-to-the-ground expertise the leader does not have.
- Subordinates return to the leader **only with distilled briefs** — blockers, decisions that require the leader's positioning, findings that change the strategic picture. Not raw work product.
- The leader's job in the console is **vision-in, decisions-out**: read distilled briefs, make calls, update bets. Never inspect raw diffs or read minute details.

**Recursive org structure (long-term):**

The CEO → C-suite split is just the first level. The system is designed to extend recursively:

- A CTO with too much engineering load spawns **VPs of Engineering** to manage clusters of work.
- VPs spawn **engineers** for individual tasks.
- The same pattern applies to CMO → marketing leads → marketers, CPO → product managers, Chief Scientist → research leads, etc.

At every level, the same contract holds: subordinates execute independently, return distilled briefs, leader makes positioning calls. Each leader has their own console view scoped to their direct reports.

**Implications for design:**

- Roles in `.cns/config.yaml` are nodes in a tree (`reports_to` is meaningful even when v1 only uses one level).
- Every artifact produced by a subordinate carries **two payloads**: the work product (in the workspace) and a **distilled brief** (in the leader's review queue). The brief is what the leader reads; the work product exists in case they want to drill in.
- The review queue is **per-leader** in shape, even when v1 implements it for one leader. `Brain/Reviews/` today; `Brain/Reviews/<leader-id>/` when the tree deepens.
- Detection, conflicts, and `/spar` operate at the leader's altitude: they surface contradictions and decisions, not implementation noise.

## Design principle: single console, no workspace hopping

Users should only ever need to look in **one central place** (the vault — typically `Brain/`) to inspect what's pending, what's in flight, and what needs review. They should NOT have to navigate to multiple workspaces, repos, or external folders to see state.

When designing any new feature that touches role workspaces, external repos, or background agents:

- **Surface state via sidecar markdown in the vault.** Even when an artifact lives outside the vault (e.g. code in `~/code/myapp/src/`), the user-facing entry point is a markdown summary in `Brain/` that links to it, summarizes the diff, and carries the review/conflict signal.
- **Never require the user to `cd` into a workspace to know what happened.** If the agent touched files in five repos, the review note enumerates them with snippets — the user reads the note, not the repos.
- **`/spar` and `/execute` outputs both flow through the same console pattern.** Conflicts and review entries are siblings; both live under `Brain/` and both get walked from the same kind of interactive ritual.

This applies to every future skill, CLI command, and config option in this repo.
