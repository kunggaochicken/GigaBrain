# GigaBrain — Obsidian plugin

> **The vault is the control plane.** Read pending bets, conflicts, and review briefs — and trigger CNS commands — without leaving Obsidian.

GigaBrain models your work like a company org structure: you set vision and strategic bets, role-scoped agents execute independently, and only distilled briefs requiring your decision come back up. This Obsidian plugin is the in-editor surface of that delegation console — sidebar of pending briefs and open conflicts, action bars on bet/brief/conflict files, and a bridge to the `cns` CLI.

The plugin shells out to the `cns` Python CLI and (for skill commands) to `claude code -p /<skill>`. It is **desktop-only** — there is no mobile build.

---

## Quick start (BRAT)

The plugin is distributed via [**BRAT** (Beta Reviewer's Auto-update Tool)](https://github.com/TfTHacker/obsidian42-brat) for v1. There is no community-store submission yet — see the architecture spec [§6](../docs/obsidian-architecture.md#6-packaging-plan-phase-6--gig-104) for why.

**One-paragraph install:** install BRAT from the Community Plugins browser, open its settings, click **Add Beta Plugin**, paste `https://github.com/kunggaochicken/GigaBrain` as the GitHub repo URL, and confirm. BRAT pulls `manifest.json`, `main.js`, and `styles.css` from the latest `obsidian-v*` GitHub release and drops them into `<vault>/.obsidian/plugins/gigabrain/`. Enable **GigaBrain** under *Settings → Community plugins*. BRAT will keep you on the latest release automatically.

Step-by-step:

1. **Install BRAT.** Open *Settings → Community plugins → Browse*, search for **BRAT**, install it, and enable it. (If Restricted Mode is on, turn it off first.)
2. **Add GigaBrain as a beta plugin.** Open *Settings → BRAT → Beta Plugin List*, click **Add Beta Plugin**, and paste:
   ```
   https://github.com/kunggaochicken/GigaBrain
   ```
   Leave the version selector at "latest". BRAT downloads the release assets.
3. **Enable the plugin.** Open *Settings → Community plugins*, find **GigaBrain** in the installed list, and toggle it on.
4. **Configure.** Open *Settings → GigaBrain* — see the [Settings walkthrough](#settings-walkthrough) below.

## Manual install (fallback)

If you don't want BRAT, install by hand from the GitHub release artifacts.

1. Go to the [Releases page](https://github.com/kunggaochicken/GigaBrain/releases) and pick the latest `obsidian-v*` tag.
2. Download the three files: `manifest.json`, `main.js`, `styles.css`.
3. Drop all three into `<your-vault>/.obsidian/plugins/gigabrain/` (create the folder if it does not exist).
4. In Obsidian: *Settings → Community plugins → click the refresh icon → enable* **GigaBrain**.

You will need to repeat steps 1–3 to update; BRAT exists precisely to automate this.

---

## First-run instructions

Once enabled:

1. **Install the `cns` CLI** (if you haven't already):
   ```bash
   pip install git+https://github.com/kunggaochicken/GigaBrain.git
   ```
2. **Open the plugin settings.** *Settings → GigaBrain*. You should see:
   - **Vault path** with a `✓` and your vault's absolute path.
   - **cns binary path** with a `✓`, the resolved path, and the version line printed by `cns --version`.
3. **Open the GigaBrain sidebar.** Click the brain ribbon icon on the left edge of the Obsidian window. The sidebar pane opens with three sections: **Pending briefs**, **Open conflicts**, **Stale bets**. If your vault is empty of bets, the sections are blank and a "Last scan" footer line appears — that's expected.
4. **Author your first bet** (in your terminal or via the Claude Code skill):
   ```bash
   cd path/to/your/vault
   cns bootstrap
   # then either:
   #   /bet                  (in Claude Code — conversational authoring)
   # or copy the template:
   cp /path/to/cns/templates/bet.md.template Brain/Bets/bet_my_first.md
   $EDITOR Brain/Bets/bet_my_first.md
   cns reindex
   ```
5. **Open the bet file in Obsidian.** A small action bar appears above the bet body in reading mode: `[Dispatch]`, `[Spar]`, `[Open bet]`. Hit `[Dispatch]` to run `/execute` against this bet — output streams into a modal log.

---

## Settings walkthrough

Open *Settings → GigaBrain*. Every field below maps to a key in `loadData()`-persisted plugin settings.

- **Vault path** — auto-detected from Obsidian's `FileSystemAdapter`. Read-only. A `✓` confirms desktop mode (the only supported mode); a `✗` would indicate the plugin is running on mobile or a non-filesystem adapter, which is unsupported per `manifest.json`'s `isDesktopOnly: true`.

- **cns binary path** (`cnsBinaryPath`) — leave blank to auto-discover. Resolution order:
  1. The override you typed in this field, if non-empty.
  2. `~/.local/bin/cns` (the documented `pip install --user` location).
  3. `which cns` on `$PATH`.

  A `✓` plus the resolved path and version line below it confirms the bridge is live. A `✗` shows an actionable error (install command, suggested override). Changing this field re-probes immediately.

- **Debug logging** (`debugLogging`) — when on, the plugin emits verbose diagnostic logs to the developer console (open with `Cmd+Opt+I` on macOS, `Ctrl+Shift+I` on Windows/Linux). Leave off for normal use; turn on when filing a bug.

- **Bets directory** (`betsDir`, default `Brain/Bets`) — vault-relative folder where `bet_*.md` files live. The sidebar's **Stale bets** section globs `<betsDir>/bet_*.md`; the auto-reindex watcher (GIG-102) listens for `modify` events under this path and runs `cns reindex --check` after a 1500ms idle.

- **Reviews directory** (`reviewsDir`, default `Brain/Reviews`) — vault-relative folder where pending agent briefs land at `<reviewsDir>/<bet-slug>/brief.md`. The sidebar's **Pending briefs** section globs `<reviewsDir>/**/brief.md` and filters to `status: pending`. Per-leader layouts (`<reviewsDir>/<leader-id>/<slug>/brief.md`) are also recognized — both shapes resolve to the same flat list in v1.

- **Conflicts file** (`conflictsFile`, default `Brain/CONFLICTS.md`) — vault-relative path to the file `cns detect` writes. The sidebar's **Open conflicts** section parses `### C-YYYY-MM-DD-<slug>` headings out of this file; the action bar on the file injects `[Spar this]` / `[Open bet]` next to each heading.

- **Stale-after days** (`staleAfterDays`, default 30) — a bet with `status: active` whose `last_reviewed` is older than this many days is flagged as stale in the sidebar. The default of 30 is intentional — see architecture spec §7.3 for the "wallpaper risk" reasoning. Lower it if you want to be nagged sooner.

Settings persist via Obsidian's `loadData` / `saveData`.

---

## Troubleshooting

**"cns binary not found" notice on plugin load.**
The plugin couldn't resolve a binary. Open *Settings → GigaBrain*. Either install the CLI:
```bash
pip install git+https://github.com/kunggaochicken/GigaBrain.git
```
or paste an explicit path into the **cns binary path** override field.

**Action button errors with "claude: command not found".**
Skill-based actions (`[Dispatch]`, `[Spar]`, `[Edit-and-rerun]`) shell out to `claude code -p /<skill>`. Install the [Claude Code CLI](https://docs.claude.com/en/docs/claude-code) and confirm `which claude` resolves. The plugin does not currently have a configurable `claude` binary path; it must be on `$PATH`.

**Sidebar is empty even though I have bets and a `CONFLICTS.md`.**
Open *Settings → GigaBrain* and confirm **Bets directory**, **Reviews directory**, and **Conflicts file** match where your vault actually keeps these. The defaults assume the canonical `Brain/Bets` / `Brain/Reviews` / `Brain/CONFLICTS.md` layout. If you have a custom layout, update those fields.

**Vault path shows ✗.**
You're on mobile or a non-desktop adapter. The plugin is `isDesktopOnly` per manifest; this should never happen in normal desktop use.

**A bet file's action bar never appears.**
The action bar only renders in *reading mode* (preview) — source mode is intentionally left untouched so raw editing is preserved. Switch to reading mode, or split the pane.

**Bet skipped silently — no entry in the sidebar.**
The bet's frontmatter likely failed to parse. Per architecture spec §7.4, `vaultState.scan()` emits a `console.warn` with the offending path and continues — there's no in-UI badge in v1. Open the developer console (`Cmd+Opt+I` / `Ctrl+Shift+I`) and look for `GigaBrain: failed to parse frontmatter` lines. Common culprits: missing `---` fences, smart quotes around the `kill_criteria:` string, an unquoted ISO date with a colon.

**Sidebar didn't update after I edited a bet.**
Vault-event-driven re-scans are debounced 500ms; if you edited externally (e.g. via your terminal) Obsidian usually picks the change up via its own filesystem watcher within a second. If not, run *Cmd+P → "Reload app without saving"* once.

**"GigaBrain" doesn't appear in Community Plugins after BRAT install.**
BRAT's install log is in *Settings → BRAT → Console*. Check for download errors. The release tag must match `obsidian-v*` and have all three files (`manifest.json`, `main.js`, `styles.css`) attached — if a release is missing one, BRAT will refuse it.

---

## Development

Day-to-day local development uses a symlink + `npm run dev` watcher; see `docs/obsidian-architecture.md` §5 (Testing strategy) and the snippet below.

```bash
cd obsidian-plugin
npm install
npm run build                        # produces main.js
ln -s "$(pwd)" <your-vault>/.obsidian/plugins/gigabrain
# enable in Obsidian, then:
npm run dev                          # watch — rebuilds main.js on save
```

For instant reload on `main.js` changes, install [`pjeby/hot-reload`](https://github.com/pjeby/hot-reload). The `.hotreload` marker is committed in this folder.

### Scripts

```bash
npm run dev      # esbuild watch — rebuilds main.js on save
npm run build    # type-check (tsc -noEmit) then production bundle
npm test         # vitest unit tests
npm run version  # syncs manifest.json version with package.json
```

### Release process (maintainers)

1. Bump `package.json` version, run `npm run version` to sync `manifest.json`.
2. Update `CHANGELOG.md`.
3. Tag and push:
   ```bash
   git tag obsidian-v0.1.0
   git push origin obsidian-v0.1.0
   ```
4. The `obsidian-release.yml` workflow builds and attaches `manifest.json` / `main.js` / `styles.css` to the GitHub release.

### Layout

```
obsidian-plugin/
├── manifest.json          # Obsidian plugin metadata (id: "gigabrain")
├── package.json           # npm scripts + devDeps
├── tsconfig.json          # strict, ES2018 target, inline source maps
├── esbuild.config.mjs     # bundler — externals: obsidian, electron, codemirror
├── styles.css             # bundled with the release
├── .hotreload             # marker for pjeby/hot-reload
└── src/
    ├── main.ts            # Plugin class, onload/onunload
    ├── settings.ts        # GigaBrainSettings, GigaBrainSettingTab
    ├── cnsRunner.ts       # discoverBinary / probeVersion / run
    ├── vaultState.ts      # pure reducers: scan vault → VaultState
    ├── bridge/            # claudeCode.runSkill (Phase 5 sentinel-aware)
    ├── processors/        # markdown post-processors (action bars)
    ├── views/             # ItemView (sidebar), Modal (streaming log)
    └── __tests__/
```

## Linear

The plugin v1 milestones are tracked in the [GigaBrain Obsidian Plugin v1 project](https://linear.app/gigaflow/project/gigabrain-obsidian-plugin-v1-7626f28ef639/overview) (GIG-93..GIG-104).
