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
}

export const DEFAULT_SETTINGS: GigaBrainSettings = {
  cnsBinaryPath: "",
  debugLogging: false,
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
