/**
 * GigaBrainStatusBar — Phase 1 status bar item (GIG-98).
 *
 * Renders a one-glyph health indicator into Obsidian's status bar:
 *   - 🔴 N conflicts   when openConflicts.length > 0
 *   - 🟡 N pending     when pendingBriefs.length + staleBets.length > 0
 *   - 🟢 clean         when all three queues are empty
 *
 * Priority: red > yellow > green (red wins as soon as any conflict exists,
 * even if briefs/stale bets also exist — the leader goes to conflicts first).
 *
 * The hover tooltip always shows the full breakdown:
 *   "Open conflicts: X · Pending briefs: Y · Stale bets: Z"
 *
 * Refresh is driven by `pushStateToSidebar` in `main.ts` — same 500ms debounce
 * as the sidebar (architecture §2.3); we do not own a debouncer here.
 *
 * Click toggles the GigaBrain sidebar via the handler injected by main.ts
 * (`activateSidebar`), keeping Obsidian-API access out of this module.
 *
 * The class is side-effect-free until `update(state)` is called, so wiring it
 * into the plugin's onload before the first scan is safe.
 */

import type { VaultState } from "../vaultState";

export type StatusBarLevel = "green" | "yellow" | "red";

export type StatusBarBreakdown = {
  openConflicts: number;
  pendingBriefs: number;
  staleBets: number;
};

/**
 * Pure priority resolver: red > yellow > green.
 *
 * Exported for unit tests.
 */
export function pickLevel(b: StatusBarBreakdown): StatusBarLevel {
  if (b.openConflicts > 0) return "red";
  if (b.pendingBriefs > 0 || b.staleBets > 0) return "yellow";
  return "green";
}

/**
 * Format the visible status bar label given a level + breakdown.
 *
 * Red shows the conflict count ("🔴 3 conflicts").
 * Yellow shows the combined briefs+stale count ("🟡 2 pending").
 * Green is just "🟢 clean".
 */
export function formatLabel(level: StatusBarLevel, b: StatusBarBreakdown): string {
  if (level === "red") {
    const n = b.openConflicts;
    return `🔴 ${n} ${n === 1 ? "conflict" : "conflicts"}`;
  }
  if (level === "yellow") {
    const n = b.pendingBriefs + b.staleBets;
    return `🟡 ${n} pending`;
  }
  return "🟢 clean";
}

/**
 * Format the always-visible-on-hover breakdown tooltip.
 */
export function formatTooltip(b: StatusBarBreakdown): string {
  return `Open conflicts: ${b.openConflicts} · Pending briefs: ${b.pendingBriefs} · Stale bets: ${b.staleBets}`;
}

/**
 * Minimal element interface — covers what we touch on the host element.
 * Lets unit tests pass a plain object instead of a real HTMLElement, and
 * matches the production `HTMLElement` returned by `addStatusBarItem`.
 */
export type StatusBarHost = {
  setText(text: string): void;
  setAttribute(name: string, value: string): void;
  addClass?(cls: string): void;
  removeClass?(cls: string): void;
  addEventListener(event: string, handler: () => void): void;
};

/**
 * Wraps a status-bar HTMLElement and updates it in response to VaultState.
 *
 * Construction is side-effect-free; the host element is only mutated when
 * `update()` runs. Click handling is wired once in the constructor and
 * dispatched through a settable handler so callers can swap behavior without
 * re-binding the listener.
 */
export class GigaBrainStatusBar {
  private readonly host: StatusBarHost;
  private clickHandler: (() => void) | null = null;

  constructor(host: StatusBarHost) {
    this.host = host;
    host.addClass?.("gigabrain-status-bar");
    host.setAttribute("aria-label", "GigaBrain status — click to open sidebar");
    host.addEventListener("click", () => {
      this.clickHandler?.();
    });
  }

  /** Register the click handler. Replaces any previously-registered one. */
  setOnClick(handler: () => void): void {
    this.clickHandler = handler;
  }

  /**
   * Push fresh vault state to the bar. Computes level + label + tooltip and
   * mutates the host element.
   */
  update(state: VaultState): void {
    const breakdown: StatusBarBreakdown = {
      openConflicts: state.openConflicts.length,
      pendingBriefs: state.pendingBriefs.length,
      staleBets: state.staleBets.length,
    };
    const level = pickLevel(breakdown);
    this.host.setText(formatLabel(level, breakdown));
    // `title` is the standard hover tooltip in Obsidian's status bar.
    this.host.setAttribute("title", formatTooltip(breakdown));
    this.host.setAttribute("aria-label", formatTooltip(breakdown));
    // Class tagging keeps the option open for future themed styling without
    // requiring a CSS change in this PR (CLAUDE.md: don't gold-plate).
    for (const cls of ["green", "yellow", "red"]) {
      this.host.removeClass?.(`gigabrain-status-${cls}`);
    }
    this.host.addClass?.(`gigabrain-status-${level}`);
  }
}
