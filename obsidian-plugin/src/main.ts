/**
 * GigaBrain CNS Obsidian plugin — entry point.
 *
 * Phase 0 (this commit) only wires the foundation: settings, vault discovery,
 * cns binary discovery + version probe. Future phases add the sidebar pane,
 * status bar, action bars, and review/conflict surfacing — all of which read
 * from the same vault the leader is already looking at (single console).
 */

import { Notice, Plugin } from "obsidian";

import {
  DEFAULT_SETTINGS,
  GigaBrainSettings,
  GigaBrainSettingTab,
} from "./settings";
import { discoverBinary, probeVersion } from "./cnsRunner";

export default class GigaBrainPlugin extends Plugin {
  settings: GigaBrainSettings = { ...DEFAULT_SETTINGS };

  /** Resolved cns binary path, cached for the plugin lifetime. */
  cnsBinaryPath: string | null = null;
  /** Resolved cns version string, cached for the plugin lifetime. */
  cnsVersion: string | null = null;

  async onload(): Promise<void> {
    await this.loadSettings();
    this.addSettingTab(new GigaBrainSettingTab(this.app, this));
    await this.discoverCns();
  }

  onunload(): void {
    // No-op for Phase 0. Future phases will tear down sidebar leaves,
    // status bar items, file watchers, etc.
  }

  async loadSettings(): Promise<void> {
    const data = (await this.loadData()) as Partial<GigaBrainSettings> | null;
    this.settings = { ...DEFAULT_SETTINGS, ...(data ?? {}) };
  }

  async saveSettings(): Promise<void> {
    await this.saveData(this.settings);
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
}
