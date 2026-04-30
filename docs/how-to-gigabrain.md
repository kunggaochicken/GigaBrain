# The leader's loop — how to actually use GigaBrain end-to-end

This is the daily/weekly playbook for a leader using GigaBrain. It's the layer above [`getting-started.md`](./getting-started.md) (which covers bare bootstrap) and below [`examples/walkthrough-linear-layer/`](../examples/walkthrough-linear-layer/) (which is a worked example). Read this once, then keep it open until the loop is muscle memory.

## The mental model

You're the leader. Your job is **vision-in, decisions-out** — write strategic bets, read distilled briefs, walk conflicts in `/spar`, accept or reject what shipped. You do not read diffs. You do not browse the codebase. You do not open Linear (when that ships) for status. The vault is your console. Subordinate roles (CTO, CMO, CSO, …) execute below your altitude and only return distilled briefs.

The contract: if you find yourself opening a workspace repo or external tool to figure out what happened, the brief contract broke. That's a higher-priority signal than whatever you went to investigate.

## The artifacts (where things live)

| Artifact | Path | Who writes | Who reads |
|---|---|---|---|
| Bet | `Brain/Bets/bet_<slug>.md` | You (or `/bet`) | Detector, agents, you |
| Bets index | `Brain/Bets/BETS.md` | `cns reindex` | You (in Obsidian) |
| Conflict queue | `Brain/CONFLICTS.md` | `cns detect` | You (in `/spar`) |
| Brief (pending) | `Brain/Reviews/<slug>/brief.md` | Dispatched agent | You (in `/spar` or directly) |
| Staged files | `Brain/Reviews/<slug>/files/` | Dispatched agent | `cns reviews accept` |
| Archived briefs | `Brain/Reviews/.archive/<timestamp>_<slug>/` | `cns reviews accept` | You (when sparring history) |

Everything ending in `.md` is meant to be read in Obsidian. Everything else is plumbing.

## The daily loop (what you do every day)

A typical day touches the loop at most twice — once in the morning, once before signing off. The loop is **read briefs → walk conflicts → write/edit one bet, maybe**. Most days you do steps 1 and 2 and skip step 3.

### Morning (~5 min)

1. **Open `Brain/CONFLICTS.md`.** If non-empty, run `/spar` and walk each conflict to a decision (`[c]onfirm / [e]dit / [k]ill / [s]upersede / [d]efer`). Most are confirms; the detector errs toward over-reporting. Done in ≤2 minutes for a typical day.
2. **Open `Brain/Bets/BETS.md`.** Skim. You're looking for any bet whose `last_reviewed` is more than ~2 weeks old, or any new bet you don't recognize (means an agent or teammate added it).
3. **Check `Brain/Reviews/`.** Any pending briefs? Each is ~300 words. Read top to bottom. The brief's "Decisions I need from you" section is the only part that requires action — if empty, you accept; if non-empty, those are positioning calls only you can make. Run `cns reviews accept <slug>` or `cns reviews reject <slug>`.

### Evening (~5 min, optional)

4. **Run `cns detect`** if you've been editing bets, the codebase, or PRs throughout the day. This catches drift before it accumulates. (If you have a daily-report cron that runs `cns detect` automatically, you can skip this.)
5. **Write or edit a bet, if strategy actually changed.** Don't rewrite bets to capture progress — that's what briefs are for. Rewrite a bet only when intent itself shifted: a new threat, a finished kill criterion, a pivot.

That's it. Less than 15 minutes a day in normal operation.

## The weekly loop (what you do once a week)

1. **Skim `Brain/Reviews/.archive/`** for last week's accepted briefs. You're not re-reading them; you're checking whether the rate of accepts vs. rejects matches your sense of how much work is shipping.
2. **Audit one bet for staleness.** Pick the bet with the oldest `last_reviewed` and ask: still active? Should it be killed/superseded/done? If yes, edit it.
3. **Look at `cns reports`** (when you've been running for ≥1 month). Aggregates cost across briefs, time-to-decision, accept rate. This is your "how is the system performing" dashboard.

## What triggers each phase

| Phase | What triggers it | How it gets done today |
|---|---|---|
| Write/edit bet | New strategic info, a kill_criterion fired, drift in `/spar` | You, in Obsidian |
| Reindex | Bet file added/edited | `cns reindex` (terminal) |
| Detect | New code/PR/note that might contradict a bet | `cns detect` (terminal or daily cron) |
| Spar | Non-empty `CONFLICTS.md` | `/spar` (Claude Code skill) |
| Dispatch | Active bet, no pending review | `/execute <slug>` (Claude Code skill) |
| Review brief | Pending brief in `Brain/Reviews/` | Read in Obsidian, then `cns reviews accept`/`reject` (terminal) or via `/spar` |

The asymmetry is real: **reading is in Obsidian, triggering is in terminal/Claude Code**. That's the friction this design has not yet closed (see issue #36).

## Is Obsidian the right control plane?

**For reading: yes, unambiguously.** Markdown bets, briefs, conflicts, indexes, archives — all of it renders cleanly in Obsidian, supports backlinks, and gives you full-text search across your strategic history. The vault is the right *display* surface.

**For triggering: not yet.** Today, every state-changing operation (`cns reindex`, `cns detect`, `/spar`, `/execute`, `cns reviews accept`) lives outside Obsidian. You drop to terminal or Claude Code, then come back to Obsidian to read the result. That's two context switches per loop cycle, every cycle. With a busy bet portfolio it adds up.

Three ways the gap closes, in increasing order of effort:

1. **Obsidian Shell Commands plugin.** Lets you bind shell commands to hotkeys or buttons inside Obsidian. Bind `cns reindex && cns detect` to a hotkey; bind `cns reviews accept "$NOTE_TITLE"` to a button visible only on review briefs. Closes ~80% of the friction with a 5-minute setup. Recommended starting point.
2. **An Obsidian plugin specifically for GigaBrain.** Custom commands, sidebar showing pending reviews + open conflicts, in-pane buttons on bet files for "dispatch" / "spar" / "accept." Bigger build (a real Obsidian plugin), but it makes the vault the actual control plane in fact, not just intent.
3. **A vault file watcher daemon.** Lives outside Obsidian; watches `Brain/Bets/` for changes and runs `cns reindex && cns detect` automatically. Same effect as a daily cron, but reactive. Pairs well with #1 — the daemon handles the ambient case, the plugin handles the explicit triggers.

Issue [#36](https://github.com/kunggaochicken/GigaBrain/issues/36) tracks closing this gap; option (1) is the lowest-cost path and a good first move.

## How to trigger Claude Code from Obsidian

Claude Code itself runs as a CLI. Triggering it from Obsidian today means one of:

- **Obsidian Shell Commands plugin** → run `claude code "<prompt>"` (or any specific skill invocation) from a hotkey. Works today, no custom code.
- **A custom Obsidian plugin** that shells out to Claude Code on note save, frontmatter change, or button click. Real engineering effort.
- **A wrapper CLI** (e.g. a `gigabrain` binary that knows your vault path and spawns Claude Code with the right context) bound to an Obsidian Shell Commands hotkey. Best ergonomics, but you're building the wrapper.

If you're starting today and want the fastest win: install Obsidian Shell Commands, bind `cd /path/to/your/vault && cns reindex && cns detect` to a hotkey, and bind `claude code` (with no args, opens an interactive session in your vault) to another. That gets you 80% of "Obsidian as control plane" with zero custom code.

## Common gotchas (drawn from real usage)

- **Stale plugin.** `/execute`, `/bet`, `/role-setup` are in v0.4.0; older installs (v0.1.0 and earlier) only have `/cns`, `/cns-bootstrap`, `/cns-detect`, `/spar`. Run `/plugin update cns` periodically.
- **Missing `execution:` block.** `/execute` requires `cfg.execution.top_level_leader` and at least one role with `workspaces` + `persona`. The default `cns bootstrap` does not write this — add it manually or via `cns execute init`.
- **Cross-vault workspace materialization.** If a role's workspace is outside the vault, `cns reviews accept` may put files at `<vault>/<rel-path>` instead of `<workspace>/<rel-path>`. Verify with `git status` in the workspace after accepting. Tracked as [#44](https://github.com/kunggaochicken/GigaBrain/issues/44).
- **`agent_run_id` parse failure.** Briefs with unquoted ISO timestamps fail to parse because PyYAML auto-converts to `datetime`. Quote the value (`"2026-04-29T14:05:00Z"`) until [#45](https://github.com/kunggaochicken/GigaBrain/issues/45) lands.
- **Substring detector false positives.** Bets matching agent commits or PRs by token overlap, not real conflict. `[c]onfirm` in `/spar`; the noise drops as bets and the codebase mature.

## What to do when the loop feels off

Two diagnostic questions, in order:

1. **Did I open a workspace, repo, or external tool today to figure out what happened?** If yes, a brief somewhere is too vague. Find that brief, mark it as a problem, and fix the role's persona prompt — not the brief.
2. **Are conflicts piling up faster than I'm sparring them?** If yes, either bets are too vague (kill criteria not specific enough → detector matches noise), or the detector is over-reporting. Tune `detection.match_strategy` or write tighter kill criteria; do NOT just stop running detect.

The loop is supposed to be calm. If it isn't, treat that as the highest-priority signal and act on it before any other work.
