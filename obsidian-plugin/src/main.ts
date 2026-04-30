/**
 * GigaBrain CNS Obsidian plugin — entry point.
 *
 * Phase 0 wired the foundation (settings, cns binary discovery).
 * Phase 1 (this commit) adds the sidebar pane: a flat oldest-first console
 * showing pendingBriefs / openConflicts / staleBets, refreshed on debounced
 * vault events. The sidebar is the in-editor surface of the single console
 * principle (CLAUDE.md): the leader sees pending work without leaving Obsidian.
 *
 * Future phases add the status bar (GIG-98), action bars (GIG-99/100/101),
 * and auto-reindex (GIG-102).
 */

import { Notice, Plugin, TAbstractFile, WorkspaceLeaf } from "obsidian";

import {
  DEFAULT_SETTINGS,
  GigaBrainSettings,
  GigaBrainSettingTab,
  getVaultBasePath,
} from "./settings";
import { discoverBinary, probeVersion } from "./cnsRunner";
import { scan, ScanOptions, VaultState } from "./vaultState";
import { GigaBrainSidebar, SIDEBAR_VIEW_TYPE } from "./views/sidebar";
import { GigaBrainStatusBar } from "./views/statusBar";
import { betActionBar } from "./processors/betActions";
import { briefActionBar } from "./processors/briefActions";
import { BetWatcher } from "./watchers/betWatcher";

/** Vault event debounce (per architecture §2.3). */
const SCAN_DEBOUNCE_MS = 500;

export default class GigaBrainPlugin extends Plugin {
  settings: GigaBrainSettings = { ...DEFAULT_SETTINGS };

  /** Resolved cns binary path, cached for the plugin lifetime. */
  cnsBinaryPath: string | null = null;
  /** Resolved cns version string, cached for the plugin lifetime. */
  cnsVersion: string | null = null;

  /** Latest vault state — null until the first scan completes. */
  private vaultState: VaultState | null = null;
  /** Debounce timer for vault-event-driven rescans. */
  private scanTimer: ReturnType<typeof setTimeout> | null = null;
  /** Tracks an in-flight scan so two events don't race a render mid-write. */
  private scanInFlight = false;
  /** Status bar item; null until onload wires it up. */
  private statusBar: GigaBrainStatusBar | null = null;

  /** Auto-reindex watcher (GIG-102). Owns its own 1500ms debounce. */
  private betWatcher: BetWatcher | null = null;

  async onload(): Promise<void> {
    await this.loadSettings();
    this.addSettingTab(new GigaBrainSettingTab(this.app, this));
    await this.discoverCns();

    this.registerView(
      SIDEBAR_VIEW_TYPE,
      (leaf) => new GigaBrainSidebar(leaf),
    );

    this.addRibbonIcon("brain", "Open GigaBrain", () => {
      void this.activateSidebar();
    });

    this.addCommand({
      id: "open-sidebar",
      name: "Open GigaBrain sidebar",
      callback: () => {
        void this.activateSidebar();
      },
    });

    this.registerVaultWatchers();

    // Initial scan after settings load. Don't block onload on it.
    this.scheduleScan(0);

    // --- bet action bar wiring (GIG-99) ---
    // Inject [Dispatch] / [Spar] / [Open bet] above bet_*.md files in
    // reading mode. The processor itself does the trigger checks (path
    // shape + frontmatter status). Architecture §3.1.
    this.registerMarkdownPostProcessor((el, ctx) => {
      void betActionBar(el, ctx, this);
    });
    // --- end bet action bar wiring ---

    // --- brief action bar wiring (GIG-100) ---
    // Inject [Accept] / [Reject] / [Edit-and-rerun] / [View files] above
    // <reviewsDir>/**/brief.md in reading mode. The processor itself
    // validates the trigger (path shape + status:/bet: frontmatter).
    // Architecture §3.2.
    this.registerMarkdownPostProcessor((el, ctx) => {
      void briefActionBar(el, ctx, this);
    });
    // --- end brief action bar wiring ---

    // --- status bar wiring (GIG-98) ---
    // Health glyph that mirrors the sidebar's queues: red on any conflict,
    // yellow on briefs/stale-bets, green when clear. Refresh rides the same
    // 500ms vault-event debounce as the sidebar (architecture §2.3); we do
    // NOT add another scan or debouncer — `pushStateToSidebar` also pushes
    // here. Click toggles the sidebar via the same `activateSidebar`
    // lifecycle the ribbon icon uses.
    const statusEl = this.addStatusBarItem();
    this.statusBar = new GigaBrainStatusBar(statusEl);
    this.statusBar.setOnClick(() => {
      void this.activateSidebar();
    });
    // --- end status bar wiring ---

    // --- auto-reindex wiring (GIG-102) ---
    // Independent 1500ms debouncer scoped to `<betsDir>/bet_*.md` modify
    // events. Runs `cns reindex --check` then conditionally `cns reindex`.
    // Architecture §2.3 / §7.5. Deliberately separate from the 500ms
    // sidebar scan above so a long reindex never starves the UI feedback;
    // when reindex writes BETS.md/CONFLICTS.md, those modify events flow
    // through the existing 500ms debouncer above and refresh both the
    // sidebar and status bar (see pushStateToSidebar).
    //
    // Self-aliased `this` so the property getters below re-read the latest
    // cnsBinaryPath / vault root each fire (both may change post-load).
    // eslint-disable-next-line @typescript-eslint/no-this-alias
    const self = this;
    this.betWatcher = new BetWatcher({
      get cnsBinaryPath() {
        return self.cnsBinaryPath;
      },
      get vaultRoot() {
        return getVaultBasePath(self.app);
      },
      getBetsDir: () => this.settings.betsDir,
      getDebounceMs: () => this.settings.reindexDebounceMs,
      log: (msg) => this.log(msg),
    });
    this.registerEvent(
      this.app.vault.on("modify", (file: TAbstractFile) => {
        this.betWatcher?.handleModify(file.path);
      }),
    );
    // --- end auto-reindex wiring ---
  }

  onunload(): void {
    if (this.scanTimer !== null) {
      clearTimeout(this.scanTimer);
      this.scanTimer = null;
    }
    // Stop the auto-reindex watcher: cancels its debounce timer and aborts
    // any in-flight reindex child process via AbortSignal (GIG-102).
    this.betWatcher?.dispose();
    this.betWatcher = null;
    // Detach all sidebar leaves; Obsidian closes the view-type cleanly.
    this.app.workspace.detachLeavesOfType(SIDEBAR_VIEW_TYPE);
  }

  async loadSettings(): Promise<void> {
    const data = (await this.loadData()) as Partial<GigaBrainSettings> | null;
    this.settings = { ...DEFAULT_SETTINGS, ...(data ?? {}) };
  }

  async saveSettings(): Promise<void> {
    await this.saveData(this.settings);
    // Settings may have changed the watched paths or staleAfterDays; rescan.
    this.scheduleScan();
  }

  /**
   * Locate the cns binary and probe its version. Failures are logged and
   * surfaced via Notice — the plugin still loads so the user can fix the
   * binary path from the settings panel.
   */
  async discoverCns(): Promise<void> {
    try {
      const path = await discoverBinary(this.settings.cnsBinaryPath);
      const version = await probeVersion(path);
      this.cnsBinaryPath = path;
      this.cnsVersion = version;
      this.log(`cns resolved: ${path} (${version})`);
    } catch (err) {
      this.cnsBinaryPath = null;
      this.cnsVersion = null;
      const msg = err instanceof Error ? err.message : String(err);
      this.log(`cns discovery failed: ${msg}`);
      new Notice(
        "GigaBrain CNS: cns binary not found. Open plugin settings to configure.",
        8000,
      );
    }
  }

  log(message: string): void {
    if (this.settings.debugLogging) {
      console.log(`[GigaBrain CNS] ${message}`);
    }
  }

  // -------------------------------------------------------------------------
  // Sidebar lifecycle
  // -------------------------------------------------------------------------

  /**
   * Reveal the sidebar leaf in the right split, creating it if needed. If a
   * scan has completed, push the latest state immediately.
   */
  private async activateSidebar(): Promise<void> {
    const { workspace } = this.app;
    let leaf: WorkspaceLeaf | null = workspace.getLeavesOfType(SIDEBAR_VIEW_TYPE)[0] ?? null;
    if (!leaf) {
      leaf = workspace.getRightLeaf(false);
      if (leaf) {
        await leaf.setViewState({ type: SIDEBAR_VIEW_TYPE, active: true });
      }
    }
    if (leaf) {
      workspace.revealLeaf(leaf);
      this.pushStateToSidebar();
    }
  }

  private pushStateToSidebar(): void {
    if (!this.vaultState) return;
    for (const leaf of this.app.workspace.getLeavesOfType(SIDEBAR_VIEW_TYPE)) {
      const view = leaf.view;
      if (view instanceof GigaBrainSidebar) {
        view.setConflictsFile(this.settings.conflictsFile);
        view.setVaultState(this.vaultState, this.settings.staleAfterDays);
      }
    }
    // Status bar refresh rides the same scan — see GIG-98 wiring in onload().
    this.statusBar?.update(this.vaultState);
  }

  // -------------------------------------------------------------------------
  // Vault watchers + debounced scan
  // -------------------------------------------------------------------------

  private registerVaultWatchers(): void {
    const handler = (file: TAbstractFile): void => {
      if (!this.shouldRescanFor(file.path)) return;
      this.scheduleScan();
    };
    this.registerEvent(this.app.vault.on("modify", handler));
    this.registerEvent(this.app.vault.on("create", handler));
    this.registerEvent(this.app.vault.on("delete", handler));
  }

  /**
   * Filter vault events to paths that affect VaultState. We watch the bets
   * directory, the reviews directory, and the conflicts file (per §2.3).
   */
  private shouldRescanFor(path: string): boolean {
    const { betsDir, reviewsDir, conflictsFile } = this.settings;
    if (path === conflictsFile) return true;
    if (path.startsWith(`${betsDir}/`) || path === betsDir) return true;
    if (path.startsWith(`${reviewsDir}/`) || path === reviewsDir) return true;
    return false;
  }

  /** Schedule a debounced scan. Pass 0 for an immediate (still async) scan. */
  private scheduleScan(delayMs: number = SCAN_DEBOUNCE_MS): void {
    if (this.scanTimer !== null) {
      clearTimeout(this.scanTimer);
    }
    this.scanTimer = setTimeout(() => {
      this.scanTimer = null;
      void this.runScan();
    }, delayMs);
  }

  private async runScan(): Promise<void> {
    if (this.scanInFlight) {
      // Another scan finished or is mid-flight; coalesce by re-scheduling.
      this.scheduleScan();
      return;
    }
    const vaultRoot = getVaultBasePath(this.app);
    if (!vaultRoot) {
      this.log("scan skipped: no vault base path (mobile?)");
      return;
    }
    this.scanInFlight = true;
    try {
      const opts: ScanOptions = {
        vaultRoot,
        reviewsDir: this.settings.reviewsDir,
        conflictsFile: this.settings.conflictsFile,
        betsDir: this.settings.betsDir,
        staleAfterDays: this.settings.staleAfterDays,
        today: new Date(),
      };
      this.vaultState = await scan(opts);
      this.log(
        `scan complete: ${this.vaultState.pendingBriefs.length} briefs, ${this.vaultState.openConflicts.length} conflicts, ${this.vaultState.staleBets.length} stale`,
      );
      this.pushStateToSidebar();
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      console.error(`[GigaBrain CNS] scan failed: ${msg}`);
    } finally {
      this.scanInFlight = false;
    }
  }
}
