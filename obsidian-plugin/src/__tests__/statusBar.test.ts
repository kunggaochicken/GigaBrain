/**
 * Tests for `views/statusBar` — covers the priority logic (red > yellow > green)
 * and the label/tooltip formatting that the leader actually reads.
 *
 * The class wires a click handler against a structural `StatusBarHost`, so we
 * pass a hand-rolled fake element that records every mutation. No Obsidian
 * stub is needed beyond the alias already in `vitest.config.ts` — but this
 * file does not import `obsidian` at all; it only depends on `VaultState`
 * (a pure type) and the status-bar module under test.
 */

import { describe, expect, it } from "vitest";

import type { VaultState } from "../vaultState";
import {
  GigaBrainStatusBar,
  StatusBarHost,
  formatLabel,
  formatTooltip,
  pickLevel,
} from "../views/statusBar";

function makeState(
  partial: Partial<{
    pendingBriefs: number;
    openConflicts: number;
    staleBets: number;
  }>,
): VaultState {
  const pending = partial.pendingBriefs ?? 0;
  const conflicts = partial.openConflicts ?? 0;
  const stale = partial.staleBets ?? 0;
  return {
    pendingBriefs: Array.from({ length: pending }, (_, i) => ({
      briefPath: `Brain/Reviews/b${i}/brief.md`,
      betSlug: `b${i}`,
      owner: "ceo",
      agentRunId: `2026-04-29T0${i}:00:00Z`,
      proposedClosure: false,
    })),
    openConflicts: Array.from({ length: conflicts }, (_, i) => ({
      id: `C-2026-04-29-c${i}`,
      betFile: `bet_c${i}.md`,
      owner: "ceo",
      firstDetected: "2026-04-29",
      daysOpen: 0,
      trigger: "",
      anchor: `C-2026-04-29-c${i}`,
    })),
    staleBets: Array.from({ length: stale }, (_, i) => ({
      betPath: `Brain/Bets/bet_s${i}.md`,
      slug: `s${i}`,
      owner: "ceo",
      lastReviewed: "2026-01-01",
      daysSinceReview: 119,
      killCriteriaUnspecified: false,
    })),
    generation: 1,
    scannedAt: Date.now(),
  };
}

/**
 * In-memory `StatusBarHost` that records every mutation so tests can assert
 * against the latest state (text, tooltip, class set).
 */
class FakeHost implements StatusBarHost {
  text = "";
  attrs = new Map<string, string>();
  classes = new Set<string>();
  clickHandlers: Array<() => void> = [];

  setText(text: string): void {
    this.text = text;
  }
  setAttribute(name: string, value: string): void {
    this.attrs.set(name, value);
  }
  addClass(cls: string): void {
    this.classes.add(cls);
  }
  removeClass(cls: string): void {
    this.classes.delete(cls);
  }
  addEventListener(event: string, handler: () => void): void {
    if (event === "click") {
      this.clickHandlers.push(handler);
    }
  }
  fireClick(): void {
    for (const h of this.clickHandlers) h();
  }
}

describe("pickLevel — priority red > yellow > green", () => {
  it("returns red whenever any conflict is open, even alongside other queues", () => {
    expect(pickLevel({ openConflicts: 1, pendingBriefs: 0, staleBets: 0 })).toBe("red");
    expect(pickLevel({ openConflicts: 1, pendingBriefs: 5, staleBets: 5 })).toBe("red");
    expect(pickLevel({ openConflicts: 7, pendingBriefs: 0, staleBets: 99 })).toBe("red");
  });

  it("returns yellow on pending briefs alone", () => {
    expect(pickLevel({ openConflicts: 0, pendingBriefs: 2, staleBets: 0 })).toBe("yellow");
  });

  it("returns yellow on stale bets alone", () => {
    expect(pickLevel({ openConflicts: 0, pendingBriefs: 0, staleBets: 3 })).toBe("yellow");
  });

  it("returns yellow when both briefs and stale bets are non-zero", () => {
    expect(pickLevel({ openConflicts: 0, pendingBriefs: 2, staleBets: 3 })).toBe("yellow");
  });

  it("returns green only when every queue is empty", () => {
    expect(pickLevel({ openConflicts: 0, pendingBriefs: 0, staleBets: 0 })).toBe("green");
  });
});

describe("formatLabel", () => {
  it("uses singular 'conflict' when there is exactly one", () => {
    expect(
      formatLabel("red", { openConflicts: 1, pendingBriefs: 0, staleBets: 0 }),
    ).toBe("🔴 1 conflict");
  });

  it("uses plural 'conflicts' for >1", () => {
    expect(
      formatLabel("red", { openConflicts: 3, pendingBriefs: 0, staleBets: 0 }),
    ).toBe("🔴 3 conflicts");
  });

  it("sums briefs + stale into the yellow 'pending' count", () => {
    expect(
      formatLabel("yellow", { openConflicts: 0, pendingBriefs: 2, staleBets: 3 }),
    ).toBe("🟡 5 pending");
  });

  it("renders green as a fixed all-clear string", () => {
    expect(
      formatLabel("green", { openConflicts: 0, pendingBriefs: 0, staleBets: 0 }),
    ).toBe("🟢 clean");
  });
});

describe("formatTooltip", () => {
  it("always shows the full breakdown regardless of zeros", () => {
    expect(
      formatTooltip({ openConflicts: 0, pendingBriefs: 0, staleBets: 0 }),
    ).toBe("Open conflicts: 0 · Pending briefs: 0 · Stale bets: 0");
    expect(
      formatTooltip({ openConflicts: 1, pendingBriefs: 2, staleBets: 3 }),
    ).toBe("Open conflicts: 1 · Pending briefs: 2 · Stale bets: 3");
  });
});

describe("GigaBrainStatusBar.update", () => {
  it("paints red label + class when conflicts exist", () => {
    const host = new FakeHost();
    const bar = new GigaBrainStatusBar(host);
    bar.update(makeState({ openConflicts: 2, pendingBriefs: 1, staleBets: 1 }));

    expect(host.text).toBe("🔴 2 conflicts");
    expect(host.classes.has("gigabrain-status-red")).toBe(true);
    expect(host.classes.has("gigabrain-status-yellow")).toBe(false);
    expect(host.classes.has("gigabrain-status-green")).toBe(false);
    expect(host.attrs.get("title")).toBe(
      "Open conflicts: 2 · Pending briefs: 1 · Stale bets: 1",
    );
  });

  it("paints yellow when only briefs/stale exist", () => {
    const host = new FakeHost();
    const bar = new GigaBrainStatusBar(host);
    bar.update(makeState({ pendingBriefs: 2, staleBets: 1 }));

    expect(host.text).toBe("🟡 3 pending");
    expect(host.classes.has("gigabrain-status-yellow")).toBe(true);
    expect(host.classes.has("gigabrain-status-red")).toBe(false);
  });

  it("paints green when every queue is empty", () => {
    const host = new FakeHost();
    const bar = new GigaBrainStatusBar(host);
    bar.update(makeState({}));

    expect(host.text).toBe("🟢 clean");
    expect(host.classes.has("gigabrain-status-green")).toBe(true);
    expect(host.classes.has("gigabrain-status-yellow")).toBe(false);
    expect(host.classes.has("gigabrain-status-red")).toBe(false);
  });

  it("clears the previous level's class on each update", () => {
    const host = new FakeHost();
    const bar = new GigaBrainStatusBar(host);

    bar.update(makeState({ openConflicts: 1 }));
    expect(host.classes.has("gigabrain-status-red")).toBe(true);

    bar.update(makeState({ pendingBriefs: 1 }));
    expect(host.classes.has("gigabrain-status-red")).toBe(false);
    expect(host.classes.has("gigabrain-status-yellow")).toBe(true);

    bar.update(makeState({}));
    expect(host.classes.has("gigabrain-status-yellow")).toBe(false);
    expect(host.classes.has("gigabrain-status-green")).toBe(true);
  });
});

describe("GigaBrainStatusBar — click + side-effects", () => {
  it("does not mutate the host until update() is called", () => {
    const host = new FakeHost();
    new GigaBrainStatusBar(host);
    expect(host.text).toBe("");
    // The constructor sets aria-label + the gigabrain-status-bar class for
    // accessibility/structure, but does NOT pick a level glyph yet.
    expect(host.classes.has("gigabrain-status-bar")).toBe(true);
    expect(host.classes.has("gigabrain-status-green")).toBe(false);
    expect(host.classes.has("gigabrain-status-yellow")).toBe(false);
    expect(host.classes.has("gigabrain-status-red")).toBe(false);
  });

  it("invokes the registered click handler when the host fires click", () => {
    const host = new FakeHost();
    const bar = new GigaBrainStatusBar(host);
    let clicked = 0;
    bar.setOnClick(() => {
      clicked += 1;
    });
    host.fireClick();
    host.fireClick();
    expect(clicked).toBe(2);
  });

  it("ignores clicks before any handler is registered", () => {
    const host = new FakeHost();
    new GigaBrainStatusBar(host);
    // Should not throw.
    host.fireClick();
  });

  it("setOnClick replaces (not adds) the handler", () => {
    const host = new FakeHost();
    const bar = new GigaBrainStatusBar(host);
    let a = 0;
    let b = 0;
    bar.setOnClick(() => {
      a += 1;
    });
    bar.setOnClick(() => {
      b += 1;
    });
    host.fireClick();
    expect(a).toBe(0);
    expect(b).toBe(1);
  });
});
