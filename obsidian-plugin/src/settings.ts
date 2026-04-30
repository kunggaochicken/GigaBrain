/**
 * Settings panel for the GigaBrain CNS plugin.
 *
 * Design intent (see CLAUDE.md, "single console / vault as control plane"):
 * the leader stays inside Obsidian. Every label here reinforces that the vault
 * IS the control plane — the panel only exposes the bridge from Obsidian to
 * the cns CLI, not extra surfaces the leader has to think about.
 */

import {
  App,
  FileSystemAdapter,
  PluginSettingTab,
  Setting,
} from "obsidian";

import type GigaBrainPlugin from "./main";
import { discoverBinary, probeVersion } from "./cnsRunner";

export interface GigaBrainSettings {
  /** Optional explicit override path to the `cns` binary. */
  cnsBinaryPath: string;
  /** Verbose console logging for plugin diagnostics. */
  debugLogging: boolean;

  // ---- Vault layout (consumed by vaultState.scan) ----
  /** Vault-relative directory containing per-bet review queues. */
  reviewsDir: string;
  /** Vault-relative path to the conflicts file. */
  conflictsFile: string;
  /** Vault-relative directory containing `bet_*.md` files. */
  betsDir: string;
  /** A bet is "stale" when `last_reviewed` is older than this many days. */
  staleAfterDays: number;
  /**
   * Debounce window in ms for the auto-reindex watcher (Phase 4 / GIG-102).
   * 1500ms is the architecture §2.3 / §7.5 ratified default; raise to ~3000ms
   * if the watcher feels too eager during heavy editing.
   */
  reindexDebounceMs: number;
}

export const DEFAULT_SETTINGS: GigaBrainSettings = {
  cnsBinaryPath: "",
  debugLogging: false,
  reviewsDir: "Brain/Reviews",
  conflictsFile: "Brain/CONFLICTS.md",
  betsDir: "Brain/Bets",
  staleAfterDays: 30,
  reindexDebounceMs: 1500,
};

/**
 * Read the vault's absolute path on disk. Obsidian only exposes this on
 * desktop (via FileSystemAdapter). On mobile this returns null, but the
 * plugin is desktop-only per manifest.
 */
export function getVaultBasePath(app: App): string | null {
  const adapter = app.vault.adapter;
  if (adapter instanceof FileSystemAdapter) {
    return adapter.getBasePath();
  }
  return null;
}

const CHECK = "✓";
const CROSS = "✗";

export class GigaBrainSettingTab extends PluginSettingTab {
  plugin: GigaBrainPlugin;

  constructor(app: App, plugin: GigaBrainPlugin) {
    super(app, plugin);
    this.plugin = plugin;
  }

  display(): void {
    const { containerEl } = this;
    containerEl.empty();

    containerEl.createEl("h2", { text: "GigaBrain CNS" });
    containerEl.createEl("p", {
      text:
        "The vault is your control plane. This panel wires Obsidian to the cns CLI so you can read briefs and trigger commands without leaving the editor.",
    });

    this.renderVaultPath(containerEl);
    this.renderBinaryPath(containerEl);
    this.renderVaultLayout(containerEl);
    this.renderDebugToggle(containerEl);
  }

  private renderVaultPath(containerEl: HTMLElement): void {
    const vaultPath = getVaultBasePath(this.app);
    const ok = vaultPath !== null;
    const display = vaultPath ?? "(unavailable — desktop only)";

    new Setting(containerEl)
      .setName("Vault path")
      .setDesc(
        "The folder cns will operate on. Detected from Obsidian — read only.",
      )
      .addText((text) => {
        text
          .setValue(display)
          .setDisabled(true);
        text.inputEl.style.width = "28em";
      })
      .then((s) => {
        const status = s.controlEl.createSpan({ cls: "gigabrain-status" });
        status.style.marginLeft = "0.5em";
        status.setText(ok ? CHECK : CROSS);
        status.style.color = ok ? "var(--color-green)" : "var(--color-red)";
      });
  }

  private renderBinaryPath(containerEl: HTMLElement): void {
    const setting = new Setting(containerEl)
      .setName("cns binary path")
      .setDesc(
        "Optional override. Leave blank to auto-discover (~/.local/bin/cns, then $PATH).",
      )
      .addText((text) => {
        text
          .setPlaceholder("/usr/local/bin/cns")
          .setValue(this.plugin.settings.cnsBinaryPath)
          .onChange(async (value) => {
            this.plugin.settings.cnsBinaryPath = value.trim();
            await this.plugin.saveSettings();
            await refreshStatus();
          });
        text.inputEl.style.width = "28em";
      });

    const status = setting.controlEl.createSpan({ cls: "gigabrain-status" });
    status.style.marginLeft = "0.5em";

    const versionLine = containerEl.createEl("div", {
      cls: "setting-item-description",
    });
    versionLine.style.marginTop = "-0.5em";
    versionLine.style.marginLeft = "1em";

    const refreshStatus = async (): Promise<void> => {
      status.setText("…");
      status.style.color = "";
      versionLine.setText("Probing…");
      try {
        const path = await discoverBinary(this.plugin.settings.cnsBinaryPath);
        const version = await probeVersion(path);
        this.plugin.cnsBinaryPath = path;
        status.setText(CHECK);
        status.style.color = "var(--color-green)";
        versionLine.setText(`Resolved: ${path} — ${version}`);
      } catch (err) {
        this.plugin.cnsBinaryPath = null;
        status.setText(CROSS);
        status.style.color = "var(--color-red)";
        const msg = err instanceof Error ? err.message : String(err);
        versionLine.setText(msg);
      }
    };

    void refreshStatus();
  }

  private renderVaultLayout(containerEl: HTMLElement): void {
    containerEl.createEl("h3", { text: "Vault layout" });
    containerEl.createEl("p", {
      cls: "setting-item-description",
      text:
        "Where the plugin looks for bets, briefs, and conflicts. Defaults match the cns CLI's `Brain/` layout.",
    });

    new Setting(containerEl)
      .setName("Bets directory")
      .setDesc("Vault-relative directory containing bet_*.md files.")
      .addText((text) =>
        text
          .setPlaceholder("Brain/Bets")
          .setValue(this.plugin.settings.betsDir)
          .onChange(async (value) => {
            this.plugin.settings.betsDir = value.trim() || "Brain/Bets";
            await this.plugin.saveSettings();
          }),
      );

    new Setting(containerEl)
      .setName("Reviews directory")
      .setDesc("Vault-relative directory containing per-bet review queues.")
      .addText((text) =>
        text
          .setPlaceholder("Brain/Reviews")
          .setValue(this.plugin.settings.reviewsDir)
          .onChange(async (value) => {
            this.plugin.settings.reviewsDir = value.trim() || "Brain/Reviews";
            await this.plugin.saveSettings();
          }),
      );

    new Setting(containerEl)
      .setName("Conflicts file")
      .setDesc("Vault-relative path to the conflicts file.")
      .addText((text) =>
        text
          .setPlaceholder("Brain/CONFLICTS.md")
          .setValue(this.plugin.settings.conflictsFile)
          .onChange(async (value) => {
            this.plugin.settings.conflictsFile =
              value.trim() || "Brain/CONFLICTS.md";
            await this.plugin.saveSettings();
          }),
      );

    new Setting(containerEl)
      .setName("Stale after (days)")
      .setDesc(
        "A bet is flagged stale if last_reviewed is older than this many days. Default 30.",
      )
      .addText((text) =>
        text
          .setPlaceholder("30")
          .setValue(String(this.plugin.settings.staleAfterDays))
          .onChange(async (value) => {
            const n = Number.parseInt(value, 10);
            this.plugin.settings.staleAfterDays =
              Number.isFinite(n) && n > 0 ? n : 30;
            await this.plugin.saveSettings();
          }),
      );

    new Setting(containerEl)
      .setName("Auto-reindex debounce (ms)")
      .setDesc(
        "Wait this long after the last bet edit before running `cns reindex`. Default 1500. Raise if reindex storms during typing.",
      )
      .addText((text) =>
        text
          .setPlaceholder("1500")
          .setValue(String(this.plugin.settings.reindexDebounceMs))
          .onChange(async (value) => {
            const n = Number.parseInt(value, 10);
            this.plugin.settings.reindexDebounceMs =
              Number.isFinite(n) && n >= 0 ? n : 1500;
            await this.plugin.saveSettings();
          }),
      );
  }

  private renderDebugToggle(containerEl: HTMLElement): void {
    new Setting(containerEl)
      .setName("Debug logging")
      .setDesc("Verbose plugin logs to the developer console.")
      .addToggle((toggle) =>
        toggle
          .setValue(this.plugin.settings.debugLogging)
          .onChange(async (value) => {
            this.plugin.settings.debugLogging = value;
            await this.plugin.saveSettings();
          }),
      );
  }
}
