/**
 * GigaBrainSidebar — Phase 1 ItemView.
 *
 * Renders three sections (flat oldest-first, per ratified §7.6):
 *   - Pending briefs
 *   - Open conflicts
 *   - Stale bets (>staleAfterDays)
 *
 * The view is dumb — it owns no scanning logic. `main.ts` runs `vaultState.scan`
 * on debounced vault events and pushes the latest state via `setVaultState`
 * (named to avoid clashing with Obsidian's `View.setState`).
 *
 * Empty sections still render a muted "no X" line so the leader sees an
 * "all clear" signal — not a hidden section (CLAUDE.md single-console rule:
 * the sidebar IS the console; absence has to be visible).
 */

import { ItemView, WorkspaceLeaf } from "obsidian";

import type { BetRef, BriefRef, ConflictRef, VaultState } from "../vaultState";

export const SIDEBAR_VIEW_TYPE = "gigabrain-sidebar";

export class GigaBrainSidebar extends ItemView {
  private state: VaultState | null = null;
  /** Days threshold from settings — surfaced in the section header. */
  private staleAfterDays = 30;

  constructor(leaf: WorkspaceLeaf) {
    super(leaf);
  }

  getViewType(): string {
    return SIDEBAR_VIEW_TYPE;
  }

  getDisplayText(): string {
    return "GigaBrain";
  }

  getIcon(): string {
    return "brain";
  }

  async onOpen(): Promise<void> {
    this.render();
  }

  async onClose(): Promise<void> {
    this.contentEl.empty();
  }

  /**
   * Push a fresh VaultState. Called by main.ts after each debounced scan.
   */
  setVaultState(state: VaultState, staleAfterDays: number): void {
    this.state = state;
    this.staleAfterDays = staleAfterDays;
    this.render();
  }

  // -------------------------------------------------------------------------
  // Rendering
  // -------------------------------------------------------------------------

  private render(): void {
    const root = this.contentEl;
    root.empty();
    root.addClass("gigabrain-sidebar");

    const heading = root.createEl("div", { cls: "gigabrain-sidebar-heading" });
    heading.createEl("h3", { text: "GigaBrain" });

    if (!this.state) {
      root.createEl("p", {
        cls: "gigabrain-sidebar-empty",
        text: "Scanning vault…",
      });
      return;
    }

    this.renderBriefs(root, this.state.pendingBriefs);
    this.renderConflicts(root, this.state.openConflicts);
    this.renderStale(root, this.state.staleBets);
    this.renderFooter(root, this.state.scannedAt);
  }

  private renderBriefs(root: HTMLElement, briefs: BriefRef[]): void {
    const section = root.createEl("section", { cls: "gigabrain-sidebar-section" });
    section.createEl("h4", {
      text: `Pending briefs (${briefs.length})`,
    });
    if (briefs.length === 0) {
      section.createEl("p", {
        cls: "gigabrain-sidebar-empty",
        text: "No pending briefs.",
      });
      return;
    }
    const ul = section.createEl("ul", { cls: "gigabrain-sidebar-list" });
    for (const brief of briefs) {
      const li = ul.createEl("li");
      const link = li.createEl("a", {
        cls: "gigabrain-sidebar-link",
        text: brief.betSlug,
        href: "#",
      });
      link.addEventListener("click", (evt) => {
        evt.preventDefault();
        this.openLink(brief.briefPath);
      });
    }
  }

  private renderConflicts(root: HTMLElement, conflicts: ConflictRef[]): void {
    const section = root.createEl("section", { cls: "gigabrain-sidebar-section" });
    section.createEl("h4", {
      text: `Open conflicts (${conflicts.length})`,
    });
    if (conflicts.length === 0) {
      section.createEl("p", {
        cls: "gigabrain-sidebar-empty",
        text: "No open conflicts.",
      });
      return;
    }
    const ul = section.createEl("ul", { cls: "gigabrain-sidebar-list" });
    for (const conflict of conflicts) {
      const li = ul.createEl("li");
      const link = li.createEl("a", {
        cls: "gigabrain-sidebar-link",
        text: conflict.id,
        href: "#",
      });
      // Deep-link to the conflict's anchor inside CONFLICTS.md so the leader
      // lands on the right heading, not the top of the file.
      const targetPath = this.conflictsLinkTarget(conflict.anchor);
      link.addEventListener("click", (evt) => {
        evt.preventDefault();
        this.openLink(targetPath);
      });
    }
  }

  private renderStale(root: HTMLElement, bets: BetRef[]): void {
    const section = root.createEl("section", { cls: "gigabrain-sidebar-section" });
    section.createEl("h4", {
      text: `Stale bets >${this.staleAfterDays}d (${bets.length})`,
    });
    if (bets.length === 0) {
      section.createEl("p", {
        cls: "gigabrain-sidebar-empty",
        text: "No stale bets.",
      });
      return;
    }
    const ul = section.createEl("ul", { cls: "gigabrain-sidebar-list" });
    for (const bet of bets) {
      const li = ul.createEl("li");
      const link = li.createEl("a", {
        cls: "gigabrain-sidebar-link",
        text: bet.slug,
        href: "#",
      });
      link.addEventListener("click", (evt) => {
        evt.preventDefault();
        this.openLink(bet.betPath);
      });
      const suffix = li.createEl("span", { cls: "gigabrain-sidebar-suffix" });
      const dayLabel = Number.isFinite(bet.daysSinceReview)
        ? `${bet.daysSinceReview}d`
        : "never";
      suffix.setText(` · ${dayLabel}`);
    }
  }

  private renderFooter(root: HTMLElement, scannedAt: number): void {
    const footer = root.createEl("footer", { cls: "gigabrain-sidebar-footer" });
    footer.setText(`Last scanned ${formatRelative(scannedAt, Date.now())}`);
  }

  // -------------------------------------------------------------------------
  // Helpers
  // -------------------------------------------------------------------------

  /**
   * `openLinkText` accepts a vault-relative path with optional `#anchor`.
   */
  private openLink(linkText: string): void {
    this.app.workspace.openLinkText(linkText, "", false);
  }

  /**
   * The conflicts file lives at a configurable path; we don't have direct
   * settings access here, so callers pass the anchor and we synthesize a
   * link target. main.ts pushes the conflicts file path on each render via
   * a separate hook if/when the path becomes user-configurable per-render.
   * For v1 the anchor is sufficient — Obsidian resolves `CONFLICTS.md#anchor`.
   */
  private conflictsLinkTarget(anchor: string): string {
    // We rely on `setConflictsFile` being called when the state is pushed.
    return `${this.conflictsFile}#${anchor}`;
  }

  private conflictsFile = "Brain/CONFLICTS.md";

  setConflictsFile(path: string): void {
    this.conflictsFile = path;
  }
}

/**
 * Render a coarse "5m ago" / "2h ago" style relative time string.
 */
function formatRelative(then: number, now: number): string {
  const seconds = Math.max(0, Math.floor((now - then) / 1000));
  if (seconds < 5) return "just now";
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}
