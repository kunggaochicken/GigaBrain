# GigaBrain Obsidian Plugin v1 — Architecture

Status: locked-in spec for Phases 1–6. Do not relitigate without an issue.
Audience: agents picking up GIG-93..GIG-104.
Scope: v1 only. Recursive org-tree work (multi-leader queues, deeper-than-CEO consoles) is explicitly out of scope per CLAUDE.md.

The plugin's job is to make the GigaBrain vault a real **delegation console inside Obsidian**: pending briefs, open conflicts, and stale bets are visible at a glance, every action the leader needs is on a button next to the artifact, and nothing requires leaving Obsidian. From `CLAUDE.md`:

> "Users should only ever need to look in **one central place** (the vault — typically `Brain/`) to inspect what's pending, what's in flight, and what needs review. They should NOT have to navigate to multiple workspaces, repos, or external folders to see state."

The plugin is the in-editor surface of that single console. Every feature in this spec exists to keep the leader from `cd`-ing anywhere.

---

## 1. Architecture overview

### 1.1 Module map

```
src/
  main.ts                  # plugin lifecycle (onload/onunload), registers everything
  settings.ts              # GigaBrainSettings (CLI path, vault root, debounces, debug toggle)
  cnsRunner.ts             # spawn wrapper around `cns` CLI; structured stdout/stderr capture
  vaultState.ts            # pure reducers: scan vault → VaultState; no Obsidian APIs
  views/
    sidebar.ts             # ItemView "GigaBrain" — pendingBriefs / openConflicts / staleBets
    statusBar.ts           # status bar item: "GB: 3 conflicts • 2 reviews • 1 stale"
  processors/
    betActions.ts          # markdown post-processor: action bar on bet_*.md
    briefActions.ts        # markdown post-processor: action bar on brief.md
    conflictsActions.ts    # markdown post-processor: action bar on CONFLICTS.md sections
  watchers/
    betWatcher.ts          # debounced auto-reindex on bet_*.md saves (Phase 4)
  bridge/
    claudeCode.ts          # Phase 5: route skill commands through an attached claude session
                           # if one is detected, otherwise fall back to cnsRunner shell-out
  util/
    frontmatter.ts         # gray-matter wrapper, strict typed parse with safe fallbacks
    paths.ts               # vault-relative path helpers, normalization
manifest.json
styles.css
```

Hard module boundaries:

- `vaultState.ts`, `cnsRunner.ts`, `util/frontmatter.ts` are **pure** (no `app.workspace`, no `ItemView`). They are unit-testable in node without Obsidian stubs.
- Anything that touches `app.*` lives in `views/`, `processors/`, `watchers/`, or `main.ts`.
- `bridge/claudeCode.ts` is the only module that decides between in-session and shell-out execution. Every other call site goes through `bridge/claudeCode.ts.runSkill(...)`, which in turn falls back to `cnsRunner` for non-skill CLI invocations like `cns reindex`.

### 1.2 Data flow

```
                                +----------------------+
   vault edit (user or agent) → | VaultEvents          |
                                | (vault.on 'modify',  |
                                |  'create','delete')  |
                                +----------+-----------+
                                           |
                                  debounce |  500ms (sidebar/status)
                                           |  1500ms (auto-reindex; GIG-102)
                                           v
                                +----------------------+
                                | vaultState.scan()    |
                                | (pure: paths in,     |
                                |  VaultState out)     |
                                +----------+-----------+
                                           |
                       +-------------------+-------------------+
                       |                   |                   |
                       v                   v                   v
                 sidebar render       statusBar render    auto-reindex
                                                          (cnsRunner)

   user clicks button → bridge/claudeCode.runSkill(name, args)
                          |
              attached?   v   shell-out (default)
            +-------+    yes      no
            |       |     |       |
            v       |     v       v
       claude IPC   |   spawn('claude', ['code','-p', '/<skill>', ...args])
                    +─→  spawn('cns',   [<subcmd>, ...])  ← non-skill CLI
                          |
                          v
                  vault writes (CLI or skill mutates files)
                          |
                          v
                  vault.on 'modify' fires → loop closes
```

Two invariants the code must preserve:

1. **The vault is the source of truth.** `vaultState` never caches across rebuilds. Every render is recomputed from disk after a debounced batch of vault events. No in-memory drift.
2. **No write happens without a CLI or skill mediating it.** The plugin never edits a bet file, a brief, or `CONFLICTS.md` directly. All writes go through `cns` CLI or a Claude skill. This means the plugin has no parsing of body markdown — only frontmatter — and stays robust to schema changes.

### 1.3 Where the "single console" rule lives

The single-console principle is enforced structurally, not aspirationally:

- The sidebar renders a flat oldest-first list (no grouping by leader in v1; see §7.6). Each `pendingBriefs` entry links straight to `brief.md`. The brief's action bar (`processors/briefActions.ts`) carries `[Accept]`, `[Reject]`, `[Edit-and-rerun]`, `[View files]` — equivalent to the `/spar` Phase 2 menu. The leader never opens a terminal.
- `[View files]` opens the staged files in Obsidian splits (the staging tree is inside the vault). The leader does not `cd` into an external workspace.
- `processors/conflictsActions.ts` puts `[Spar this]`, `[Defer]`, `[Kill]` next to each `### C-...` heading in `CONFLICTS.md`. Action equivalents to the `/spar` Phase 1 menu.
- Auto-reindex (Phase 4) means after editing a bet in Obsidian and switching tabs, `BETS.md` is fresh. No "did I remember to reindex?" tax.

The only escape hatch is `cnsRunner.runRaw(args)`, exposed for power users via a command palette entry "GigaBrain: run cns CLI". It is a courtesy, not a workflow.

---

## 2. Vault state model

### 2.1 Shape

```ts
type VaultState = {
  pendingBriefs: BriefRef[];
  openConflicts: ConflictRef[];
  staleBets: BetRef[];
  // generation counter — incremented on every successful scan; views diff against
  // previous generation to skip pointless re-renders.
  generation: number;
  scannedAt: number; // epoch ms; surfaced in sidebar footer for trust
};

type BriefRef = {
  briefPath: string;        // vault-relative, e.g. "Brain/Reviews/foo/brief.md"
  betSlug: string;          // "foo"
  owner: string;            // role id
  agentRunId: string;       // ISO; sort key
  proposedClosure: boolean;
  costUsd?: number;         // null if frontmatter has no `cost:` block
};

type ConflictRef = {
  id: string;               // "C-2026-04-29-foo"
  betFile: string;          // "bet_foo.md"
  owner: string;
  firstDetected: string;    // ISO date
  daysOpen: number;
  trigger: string;          // first 120 chars
  // Anchor in CONFLICTS.md so the sidebar entry can deep-link via
  // app.workspace.openLinkText(`CONFLICTS.md#${anchor}`).
  anchor: string;
};

type BetRef = {
  betPath: string;          // vault-relative
  slug: string;
  owner: string;
  lastReviewed: string;     // ISO
  daysSinceReview: number;
  killCriteriaUnspecified: boolean; // matches the legacy sentinel
};
```

### 2.2 Detection rules

`vaultState.scan(vault, settings) -> VaultState` performs exactly this work:

**`pendingBriefs`:**
- Glob `<reviews_dir>/**/brief.md` where `reviews_dir = settings.reviewsDir` (default `Brain/Reviews`).
  - When per-leader layout is detected (any path matches `<reviews_dir>/<id>/<slug>/brief.md`), include both layouts; the plugin treats them as siblings without distinguishing leaders in v1 (CLAUDE.md scope).
- Filter to frontmatter `status: pending`.
- Extract `bet`, `owner`, `agent_run_id`, `proposed_closure`, `cost.usd`.
- Sort oldest-first by `agent_run_id` (matches `cns reviews list`).

**`openConflicts`:**
- Read `<conflicts_file>` (default `Brain/CONFLICTS.md`) from settings.
- Parse `### C-YYYY-MM-DD-<slug>` headings and the bullet block beneath each. Format is locked by `cns/conflicts.py:render_conflicts_file` — match against `^### (C-\d{4}-\d{2}-\d{2}-[a-z0-9_]+)\b`.
- For each: read `**Bet:**`, `**First detected:**`, `**Trigger:**` from following bullets. Owner is taken from the parent `## <Role Name> (<id>)` heading (regex `^## .+ \(([a-z0-9_-]+)\)`).
- Compute `daysOpen` against `today`.

**`staleBets`:**
- Glob `<bets_dir>/bet_*.md` (default `Brain/Bets/bet_*.md`).
- Parse frontmatter only; skip body.
- Bet is "stale" if any of:
  - `status: active` AND `kill_criteria == "unspecified — needs sparring"` (the legacy sentinel)
  - `status: active` AND `last_reviewed` older than `settings.staleAfterDays` (default 30)
  - `status: active` AND `deferred_until` is set AND `deferred_until <= today` (the deferral has expired and the bet should re-enter conflict detection)

`vaultState` does **not** parse markdown bodies. Any future need for body content goes through the CLI.

### 2.3 Debounce

Two separate debouncers (Phase 1 + Phase 4):

- **Sidebar / status bar:** 500ms after the last `vault.on('modify' | 'create' | 'delete')` event under `<bets_dir>`, `<reviews_dir>`, or `<conflicts_file>`. Triggers a `vaultState.scan()` and re-renders both views.
- **Auto-reindex (GIG-102):** 1500ms after the last `vault.on('modify')` on a path matching `<bets_dir>/bet_*.md`. Triggers `cnsRunner.run(['reindex', '--check'])`; if exit non-zero, runs `cnsRunner.run(['reindex'])`. Result is surfaced as a Notice and a status-bar tick.

Both debouncers cancel and reset on each new event, share a single per-plugin "scan in flight" lock, and skip redundant scans (an `--check` exit-zero short-circuit is the win — we only pay the reindex cost when a bet truly changed).

The 1500ms auto-reindex value is ratified for v1; if it proves too eager (causing reindex storms during typing), Phase 4 can raise it to 3000ms via settings without code change.

---

## 3. Action surface

For every file type the plugin recognizes, it injects a thin action bar via a `MarkdownPostProcessor`. The bar is rendered as the first child of the rendered markdown root, so it appears above the file's body in reading mode. (Source mode shows nothing — that's intentional; it preserves raw editing.)

Async UX rule:
- **Short ops (< 2s expected):** show a `Notice("running…")` immediately, replace with `Notice("done")` or `Notice("failed: <stderr-line-1>")` on completion.
- **Long ops (≥ 2s expected, e.g. `/execute`):** open a `Modal` with a streaming log view that pipes `cnsRunner` stdout/stderr line-by-line. Modal has a Close button; closing does not abort the underlying process (the CLI is mid-write and aborting is unsafe).

Error model:
- Every CLI invocation returns `{ exitCode, stdout, stderr }`. Non-zero exit ⇒ user-visible error.
- **Stderr is surfaced verbatim** (truncated to 2000 chars). No silent failures, no rewriting. The leader needs the same diagnostic the CLI would print at a terminal.
- A "Show full output" button on every error Notice opens the modal log retroactively.

### 3.1 Bet files (`processors/betActions.ts`)

- **Trigger condition:** rendered markdown for any file matching `<bets_dir>/bet_*.md` AND frontmatter parses successfully AND has a `status:` field.
- **Buttons (v1 — locked by §7.1):**
  - `[Dispatch]` — icon `play-circle` — runs skill `/execute` with `--bet <slug>`. Long op, modal log.
  - `[Spar]` — icon `swords` — runs skill `/spar --bet <slug>`. Skill emits its own "scoped to bet not yet supported" notice in v1 (§7.2). Long op, modal log.
  - `[Open bet]` — icon `file-text` — focuses the editor on the bet's frontmatter line. Instant; no CLI call.
- **Dropped from v1 (re-add in v2 per GIG-108):** `[Mark reviewed]`, `[Defer 7d]`.
- **Async behavior:** Dispatch and Spar are modal-log.
- **Error surface:** stderr verbatim in Notice or modal. No retries.

### 3.2 Brief files (`processors/briefActions.ts`)

- **Trigger condition:** path matches `<reviews_dir>/**/brief.md` AND frontmatter has `status:` and `bet:`.
- **Buttons (mirror `/spar` Phase 2):**
  - `[Accept]` — icon `check-circle` — runs `cns reviews accept <slug>`. Short op (filesystem move). On success, brief moves to `.archive/`; the post-processor's host file disappears, which Obsidian handles by closing the leaf.
  - `[Reject]` — icon `x-circle` — runs `cns reviews reject <slug>`. Short op.
  - `[Edit-and-rerun]` — icon `refresh-cw` — opens a small modal with a textarea ("Reviewer notes"), then on submit runs the skill `/execute` with `--bet <slug> --all` after appending the notes to the brief. Long op, modal log.
  - `[View files]` — icon `folder-open` — opens the sibling `files/` directory's contents in a new Obsidian split (uses `app.workspace.openLinkText` for each file). Instant; no CLI call.
- **Async behavior:** Accept/Reject as Notice; Edit-and-rerun as modal.
- **Error surface:** as above; if `cns reviews accept` fails (e.g. workspace path missing), surface stderr and leave the brief in place.

### 3.3 `CONFLICTS.md` (`processors/conflictsActions.ts`)

- **Trigger condition:** path equals `<conflicts_file>`.
- **Buttons (v1 — locked by §7.1):**
  - `[Spar this]` — icon `swords` — runs skill `/spar --conflict <id>`. Skill emits its own "scoped sparring not yet supported" notice in v1 (§7.2). Long op, modal log.
  - `[Open bet]` — icon `file-text` — opens the linked `[[bet_…]]` file in a new tab. Instant.
- **Dropped from v1 (re-add in v2 per GIG-108):** `[Defer 7d]`.
- **Async behavior:** Spar this as modal; Open bet is instant.
- **Error surface:** as above.

---

## 4. Claude Code bridge (Phase 5 spec)

### 4.1 Phase 2–4 baseline: shell-out

`bridge/claudeCode.runSkill(name, args)` always works via:

```ts
spawn('claude', ['code', '-p', `/${name}`, ...args], { cwd: vaultRoot })
```

Output is streamed to a modal log. This is the safety net — if the bridge cannot detect an attached session, this path fires. Phases 2–4 ship with **only** this path. Phase 5 layers detection on top; the shell-out is never removed.

### 4.2 Phase 5: detect an attached claude session

**Mechanism: sentinel file.** When a Claude Code session attaches to the vault, it writes `<vault>/.cns/.obsidian-bridge.json` containing:

```json
{
  "pid": 12345,
  "started_at": "2026-04-29T14:30:00Z",
  "socket": "/tmp/cns-bridge-12345.sock"
}
```

The plugin polls (or `vault.on('modify')`-watches) this file. If present **and** `pid` is alive **and** `started_at` is within 24h, the bridge routes via the unix-domain socket at `socket`. Otherwise it falls back to shell-out.

**Why a sentinel file** (vs env var or named pipe): Obsidian's plugin process does not inherit env from the user shell that launched Claude Code, so an env-var contract is unreliable across Obsidian-launched-from-Finder vs Obsidian-launched-from-terminal. A vault-local sentinel is reachable from both Obsidian and Claude with no out-of-band coordination, lives inside the vault git history (so a stale sentinel from a crashed session is visible and committable as a tombstone), and matches the existing `.cns/.agent-hooks/.active` pattern the executor already uses (`cns/hook_executor.py`). A named pipe was rejected because Windows support for the v2 plugin would require a parallel Windows-named-pipe path — an entire fork. The socket inside the JSON is the actual IPC; the file is just rendezvous.

The fallback ordering is fixed: **socket → shell-out**. If socket dial fails, we shell out and emit a single `console.warn` per session (not a user-facing Notice — fallback is normal).

The plugin does NOT write the sentinel; that's the Claude Code session's job (a future ticket on the cns side). The plugin only reads.

### 4.3 Bridge contract

`runSkill(name: string, args: string[]) -> AsyncIterable<{stream: 'stdout'|'stderr', line: string} | {done: true, exitCode: number}>`

Both backends conform to this iterator shape. The modal log consumes it directly. The shell-out implementation wraps `child_process.spawn`; the socket implementation frames lines per the IPC protocol the cns-side will define. Until that protocol exists, **only shell-out is wired**, and the sentinel detection is dead code with a unit test pinning the detection logic.

---

## 5. Testing strategy

### 5.1 Unit-testable surface (jest, no Obsidian)

- **`cnsRunner`:** mock `child_process.spawn`; assert command, args, cwd, env. Cover non-zero exit, stderr capture, timeout (60s default).
- **`vaultState` reducers:** feed synthetic file lists + frontmatter blobs; assert `BriefRef[]`, `ConflictRef[]`, `BetRef[]` shape. Edge cases:
  - malformed frontmatter (skip with warning, do not crash)
  - missing `last_reviewed` (treat as never-reviewed → stale)
  - `deferred_until` in the future (NOT stale)
  - per-leader path layout (both shapes resolve to the same `BriefRef`)
- **`util/frontmatter`:** locked behavior on quoted strings, dates, null fields, the `unspecified — needs sparring` sentinel (em-dash matters).
- **`bridge/claudeCode` detection:** pure — given a mock `fs.statSync`/`fs.readFileSync`, assert `attached: true|false`. PID-alive check is mockable via injected `isPidAlive(pid)`.

Target: `>=80%` line coverage on the four pure modules listed above. Not a release gate; a smell test.

### 5.2 Hard-to-test (smoke-test by hand)

- `ItemView` rendering (sidebar) — validated by hand against fixture vault.
- Markdown post-processors — same.
- Modal streaming log under real CLI — same.
- Auto-reindex debounce timing under user typing — same.

### 5.3 Fixture vault

`tests/fixtures/vault/` — checked into the repo. Minimum content:

```
.cns/config.yaml                            # solo-founder preset
Brain/
  Bets/
    BETS.md
    bet_ship_v1.md                          # active, kill_criteria specified, last_reviewed=today
    bet_open_source.md                      # active, kill_criteria="unspecified — needs sparring"
  CONFLICTS.md                              # one conflict on bet_ship_v1
  Reviews/
    ship_v1/
      brief.md                              # status: pending, proposed_closure: true
      files/main.py                         # staged
```

This fixture is the single ground truth for both unit tests (paths and frontmatter) and hand-driven smoke tests (load the fixture as an Obsidian vault, install the plugin, walk each action).

---

## 6. Packaging plan (Phase 6 / GIG-104)

- **Distribution: BRAT (Beta Reviewer's Auto-update Tool) only for v1.** No community-store submission. The cns CLI is unstable enough (schema v1→v2 migration is recent) that we don't want the broader Obsidian community filing issues yet.
- **Release artifact:** GitHub release attached to a tag `obsidian-v0.1.0`. Three files at the root of the release: `manifest.json`, `main.js`, `styles.css`.
- **Versioning:** semver. Tag prefix `obsidian-` so it does not collide with cns CLI tags (e.g. `v0.3.0` is the CLI; `obsidian-v0.1.0` is the plugin).
- **Build:** esbuild bundle, target ES2020, single-file output. No source maps in release artifact (BRAT users hit them rarely; we can revisit).
- **Install instructions** (added to `README.md` under Quick Start): one-liner for BRAT plus a manual-install fallback (drop the three files into `<vault>/.obsidian/plugins/gigabrain/`).
- **`manifest.json`:** `id: "gigabrain"`, `name: "GigaBrain"`, `minAppVersion: "1.5.0"`, `isDesktopOnly: true` (we shell out to a python CLI; mobile is out).

CI: a GitHub Actions workflow on tags matching `obsidian-v*` builds the bundle and uploads the three files to the release. No automated smoke test against a real Obsidian instance — that would require an electron harness we are not building for v1.

---

## 7. Decisions ratified (was: open questions)

These were the architect's open questions. Adversarial review (Red Team + Pragmatist) was run on a proposed answer set; the rulings below are now the locked spec for Phase 1+ implementing agents.

### 7.1 `[Mark reviewed]` and `[Defer 7d]` buttons — DROPPED FROM v1

**Decision:** the bet-file action bar in v1 ships **only** `[Dispatch]`, `[Spar]`, `[Open bet]`. The conflict action bar in v1 ships **only** `[Spar this]`, `[Open bet]`. No `[Mark reviewed]`, no `[Defer 7d]`.

**Rationale:** ~5 keystrokes saved at low frequency does not justify (a) two new CLI commands with non-trivial schema-coupling concerns (`deferred_until` is currently a *detection-rule input*, so `cns bet defer` couples CLI semantics to detector semantics), (b) a runtime CLI capability probe in the plugin to handle CLI-not-yet-shipped, (c) opening the door to "the plugin handles CLI weirdness in its own UI" as a recurring pattern. For the rare v1 case where the leader needs to bump `last_reviewed` or set `deferred_until`, they click `[Open bet]` and edit the frontmatter manually — same mechanical action minus the plumbing.

**When v2 ships:** add `cns bet touch` and (probably) `cns conflicts defer <id>` (defer at conflict-altitude is the more-correct semantics) in one PR, and the buttons in the same PR. No probe, no graceful-degrade — they ship together.

**Filed:** GIG-108 (v2 follow-up: bet review/defer CLI + buttons).

### 7.2 `/spar --bet <slug>` and `--conflict <id>` — plugin passes, skill announces

**Decision:** plugin passes the flags. The `/spar` skill itself emits a single stdout line as its first output: `Note: --conflict accepted but ignored in v1; walking full queue.` Plugin streams that to the modal log like any other skill output. Plugin contains zero defensive narration — the skill owns its own behavior surface.

**When v2 ships scoped sparring:** `/spar` stops printing the note, starts honoring the flag. Plugin code does not change.

**Filed:** GIG-109 (v2 follow-up: scoped `/spar` + drop the v1 announcement line).

### 7.3 Staleness threshold — 30 days

**Decision:** `settings.staleAfterDays` defaults to **30**. Settings-overridable. No tooltip on stale entries — the slug + `Nd` suffix is enough; the leader clicks through to read the bet.

**Why not 14:** strategic bets at quarterly or yearly horizons should go silent for stretches by design. A 14-day global default would nag the leader on slow-cycle bets weekly, train them to ignore the staleness section, and the alarm becomes wallpaper. The horizon field already exists on bet frontmatter; horizon-aware staleness is the correct shape but it is v2 work.

**Filed:** GIG-110 (v2 follow-up: horizon-aware staleness threshold).

### 7.4 Briefs-failed-to-parse — `console.warn` only, no UI

**Decision:** when `vaultState.scan` hits a parse error, `console.warn` with the path. No badge, no footer chrome, no sidebar section. If dogfooding shows real recurrence, design a real surface (likely a "GigaBrain: show diagnostics" command-palette entry) — don't add chrome speculatively.

### 7.5 Auto-reindex on save, debounced 1500ms — accepted

**Decision:** as originally specced. No modification.

### 7.6 Per-leader review queues — flat list, refactor in v2

**Decision:** sidebar renders a flat list (one `<ul>`, oldest-first). No grouping by `owner`. When v2 ships per-leader scoping the refactor is ~30 min of `groupBy` — pay it then, when the v2 UX shape is known. Group-by-owner today (with one owner) ships extra visual noise for a feature that has zero v1 value.

**Filed:** GIG-111 (v2 follow-up: leader picker + sidebar grouping).

---

### 7.7 Adversarial review record

The decisions above replaced an earlier proposal set. The losing arguments are recorded here so future agents don't re-litigate:

- **14d staleness threshold** (rejected): "wallpaper" risk on slow-cycle bets, no dogfooding evidence base.
- **Group-by-owner from day one** (rejected): premature abstraction; one-owner-with-headings is worse UX than a flat list.
- **CLI capability probe + hidden buttons** (rejected): adds plugin-side complexity for a graceful-degrade scenario that vanishes if the CLI work is sequenced before the buttons.
- **Aggregate parse-error footer badge** (rejected): half-undid the architect's clean "no"; debug aid masquerading as a workflow surface.
- **Plugin-side "scoped sparring not yet supported" header text** (rejected): plugin should not editorialize skill behavior. Moved upstream.
- **Compound pattern caught:** several modifications individually small but together established "the plugin handles CLI/data weirdness in its own UI" as a pattern, in tension with §1.2's "no write happens without a CLI or skill mediating it." Killing them all preserved the invariant.
