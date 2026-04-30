# GigaBrain CNS — Obsidian plugin

> **The vault is the control plane.** Read pending bets, conflicts, and review briefs — and trigger CNS commands — without leaving Obsidian.

This is the Phase 0 foundation. It wires Obsidian to the `cns` Python CLI so that future phases (sidebar pane, status bar, action bars, review/conflict surfacing) all share one settings panel and one binary discovery path.

## What ships in v0.1.0

- Plugin scaffold (manifest, esbuild bundler, dev/build/test scripts)
- Settings panel with vault-path display and `cns` binary discovery + version probe
- Hot-reload marker for the [`pjeby/hot-reload`](https://github.com/pjeby/hot-reload) workflow
- A `cnsRunner` module that any future feature can import to invoke CNS commands

There is intentionally no sidebar, no status bar, no commands palette entries yet. Those land in Phase 1.

## Install (development)

The plugin is not published yet. You install it by symlinking this folder into your vault's plugins directory.

1. **Build the plugin once.**
   ```bash
   cd obsidian-plugin
   npm install
   npm run build
   ```
   This produces `main.js` next to `manifest.json`.

2. **Symlink into your vault.** Replace `~/Documents/MyVault` with your actual vault path.
   ```bash
   ln -s "$(pwd)" ~/Documents/MyVault/.obsidian/plugins/gigabrain-cns
   ```

3. **Enable the plugin.** Open Obsidian → Settings → Community plugins → enable "GigaBrain CNS". (You may need to disable Restricted Mode.)

4. **Configure.** Open Settings → GigaBrain CNS. The vault path should resolve automatically. The `cns` binary path either auto-discovers or accepts an explicit override.

## Hot reload (recommended dev loop)

Install the [`pjeby/hot-reload`](https://github.com/pjeby/hot-reload) community plugin once. It watches for the `.hotreload` marker file (already committed in this repo) and reloads the plugin whenever `main.js` changes.

The dev loop:

```bash
cd obsidian-plugin
npm run dev          # esbuild watch mode — rebuilds main.js on every save
```

Edit any `src/*.ts`. esbuild rebuilds, hot-reload picks it up, Obsidian re-instantiates the plugin in place. No restart, no toggle.

## Settings walkthrough

Open Obsidian → Settings → GigaBrain CNS.

- **Vault path** — auto-detected from Obsidian's filesystem adapter. Read-only. A `✓` confirms desktop mode (the only supported mode); a `✗` would indicate something has gone wrong.
- **cns binary path** — leave blank to auto-discover. Resolution order:
  1. The override you typed in this field
  2. `~/.local/bin/cns` (the documented `pip install --user` location)
  3. `which cns` on `$PATH`
  A `✓` plus the resolved path and version line below it confirms the bridge is live. A `✗` shows an actionable error (install command, suggested override).
- **Debug logging** — toggle verbose plugin logs to the developer console (`Cmd+Opt+I`).

Settings persist via Obsidian's `loadData` / `saveData`. Changing the binary override re-probes immediately.

## Troubleshooting

**"cns binary not found" notice on plugin load.**
The plugin couldn't resolve a binary. Open Settings → GigaBrain CNS. Either install the CLI:
```bash
pip install git+https://github.com/kunggaochicken/GigaBrain.git
```
or paste an explicit path into the override field.

**Symlink visible but plugin doesn't appear.**
Make sure you symlinked the folder containing `manifest.json` (i.e. `obsidian-plugin/`), not the parent. Then in Obsidian → Settings → Community plugins, click the refresh icon.

**Hot reload isn't reloading.**
Confirm `pjeby/hot-reload` is enabled and the `.hotreload` file exists in the plugin folder. Hot-reload only watches plugins that have it.

**Vault path shows ✗.**
You're on mobile or in a non-desktop adapter. The plugin is `isDesktopOnly` per manifest; this should never happen in normal use.

## Development scripts

```bash
npm run dev      # esbuild watch — rebuilds main.js on save
npm run build    # type-check (tsc -noEmit) then production bundle
npm test         # vitest unit tests
npm run version  # syncs manifest.json version with package.json
```

## Layout

```
obsidian-plugin/
├── manifest.json          # Obsidian plugin metadata
├── package.json           # npm scripts + devDeps
├── tsconfig.json          # strict, ES2018 target, inline source maps
├── esbuild.config.mjs     # bundler — externals: obsidian, electron, codemirror
├── styles.css             # placeholder; populated in Phase 1
├── .hotreload             # marker for pjeby/hot-reload
├── .gitignore             # node_modules/, main.js, *.log, .DS_Store
└── src/
    ├── main.ts            # Plugin class, onload/onunload, discovery on load
    ├── settings.ts        # GigaBrainSettings, GigaBrainSettingTab
    ├── cnsRunner.ts       # discoverBinary / probeVersion / run
    └── __tests__/
        └── cnsRunner.test.ts
```

## Linear

Phase 0 bundles GIG-93, GIG-94, GIG-95, GIG-96 because they share scaffolding. See the [GigaBrain Obsidian Plugin v1 project](https://linear.app/gigaflow/project/gigabrain-obsidian-plugin-v1-7626f28ef639/overview).
