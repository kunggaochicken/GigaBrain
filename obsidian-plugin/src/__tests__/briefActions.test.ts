/**
 * Tests for `processors/briefActions` — pure-logic surface only.
 *
 * Modal + DOM rendering are explicitly hard-to-test (architecture §5.2);
 * we cover them by hand. These tests pin slug derivation, the trigger
 * predicate, and the locked argv shapes for accept / reject / edit-and-rerun
 * — the load-bearing decisions per spec §3.2.
 */

import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";

import {
  acceptArgs,
  deriveBriefSlug,
  editAndRerunArgs,
  isFirstSection,
  isUnderReviewsDir,
  rejectArgs,
  shouldInjectBriefBar,
} from "../processors/briefActions.predicates";

const REVIEWS_DIR = "Brain/Reviews";

const validFrontmatter = `---
status: pending
bet: ship_v1
owner: ceo
agent_run_id: 2026-04-29T14:00:00Z
---

body
`;

describe("deriveBriefSlug", () => {
  it("derives slug from the directory above brief.md (flat layout)", () => {
    expect(
      deriveBriefSlug("Brain/Reviews/ship_v1/brief.md", REVIEWS_DIR),
    ).toBe("ship_v1");
  });

  it("derives slug from the deepest dir in per-leader layout", () => {
    // <reviews>/<leader>/<slug>/brief.md — slug is still the parent dir.
    expect(
      deriveBriefSlug("Brain/Reviews/ceo/ship_v1/brief.md", REVIEWS_DIR),
    ).toBe("ship_v1");
  });

  it("preserves hyphens in slug", () => {
    expect(
      deriveBriefSlug("Brain/Reviews/open-source/brief.md", REVIEWS_DIR),
    ).toBe("open-source");
  });

  it("returns null for paths outside the reviews dir", () => {
    expect(
      deriveBriefSlug("Brain/Bets/ship_v1/brief.md", REVIEWS_DIR),
    ).toBeNull();
  });

  it("returns null when filename is not exactly brief.md", () => {
    expect(
      deriveBriefSlug("Brain/Reviews/ship_v1/notes.md", REVIEWS_DIR),
    ).toBeNull();
    expect(
      deriveBriefSlug("Brain/Reviews/ship_v1/BRIEF.md", REVIEWS_DIR),
    ).toBeNull();
  });

  it("respects a custom reviewsDir", () => {
    expect(
      deriveBriefSlug("MyVault/Queue/foo/brief.md", "MyVault/Queue"),
    ).toBe("foo");
    expect(
      deriveBriefSlug("Brain/Reviews/foo/brief.md", "MyVault/Queue"),
    ).toBeNull();
  });

  it("normalizes trailing slash on reviewsDir", () => {
    expect(
      deriveBriefSlug("Brain/Reviews/foo/brief.md", "Brain/Reviews/"),
    ).toBe("foo");
  });
});

describe("isUnderReviewsDir", () => {
  it("matches paths inside the reviews dir", () => {
    expect(
      isUnderReviewsDir("Brain/Reviews/foo/brief.md", REVIEWS_DIR),
    ).toBe(true);
  });

  it("rejects paths outside the reviews dir", () => {
    expect(
      isUnderReviewsDir("Brain/Bets/bet_foo.md", REVIEWS_DIR),
    ).toBe(false);
    // Prefix-only match (e.g. Brain/ReviewsX/...) must not pass.
    expect(
      isUnderReviewsDir("Brain/ReviewsExtra/foo/brief.md", REVIEWS_DIR),
    ).toBe(false);
  });
});

describe("shouldInjectBriefBar", () => {
  it("returns true for brief.md under reviews dir with status+bet frontmatter", () => {
    expect(
      shouldInjectBriefBar(
        "Brain/Reviews/ship_v1/brief.md",
        validFrontmatter,
        REVIEWS_DIR,
      ),
    ).toBe(true);
  });

  it("returns true under per-leader layout", () => {
    expect(
      shouldInjectBriefBar(
        "Brain/Reviews/ceo/ship_v1/brief.md",
        validFrontmatter,
        REVIEWS_DIR,
      ),
    ).toBe(true);
  });

  it("returns false for paths outside the reviews dir", () => {
    expect(
      shouldInjectBriefBar(
        "Brain/Bets/bet_foo.md",
        validFrontmatter,
        REVIEWS_DIR,
      ),
    ).toBe(false);
  });

  it("returns false when filename is not brief.md", () => {
    expect(
      shouldInjectBriefBar(
        "Brain/Reviews/ship_v1/notes.md",
        validFrontmatter,
        REVIEWS_DIR,
      ),
    ).toBe(false);
  });

  it("returns false when frontmatter is missing the status field", () => {
    const noStatus = `---
bet: ship_v1
owner: ceo
---

body
`;
    expect(
      shouldInjectBriefBar(
        "Brain/Reviews/ship_v1/brief.md",
        noStatus,
        REVIEWS_DIR,
      ),
    ).toBe(false);
  });

  it("returns false when frontmatter is missing the bet field", () => {
    const noBet = `---
status: pending
owner: ceo
---

body
`;
    expect(
      shouldInjectBriefBar(
        "Brain/Reviews/ship_v1/brief.md",
        noBet,
        REVIEWS_DIR,
      ),
    ).toBe(false);
  });

  it("returns false when frontmatter is absent entirely", () => {
    expect(
      shouldInjectBriefBar(
        "Brain/Reviews/ship_v1/brief.md",
        "no frontmatter here",
        REVIEWS_DIR,
      ),
    ).toBe(false);
  });

  describe("frontmatter parse failure path", () => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    let warnSpy: any;

    beforeEach(() => {
      warnSpy = vi
        .spyOn(console, "warn")
        .mockImplementation(() => undefined);
    });

    afterEach(() => {
      warnSpy.mockRestore();
    });

    it("warns and returns false on YAML parse error", () => {
      const broken = `---
status: "unterminated
bet: ship_v1
---

body
`;
      const result = shouldInjectBriefBar(
        "Brain/Reviews/ship_v1/brief.md",
        broken,
        REVIEWS_DIR,
      );

      expect(result).toBe(false);
      expect(warnSpy).toHaveBeenCalledOnce();
      expect(warnSpy.mock.calls[0][0]).toMatch(/frontmatter parse failed/);
    });
  });
});

describe("isFirstSection", () => {
  it("returns true at lineStart 0", () => {
    expect(isFirstSection({ lineStart: 0 })).toBe(true);
  });

  it("returns false elsewhere", () => {
    expect(isFirstSection({ lineStart: 1 })).toBe(false);
    expect(isFirstSection({ lineStart: 42 })).toBe(false);
  });

  it("returns false on null/undefined section info", () => {
    expect(isFirstSection(null)).toBe(false);
    expect(isFirstSection(undefined)).toBe(false);
  });
});

describe("CLI argv shape", () => {
  // Locked by spec §3.2. The plugin never invents flags; these argv shapes
  // are the contract with the cns CLI and the /execute skill.
  it("acceptArgs is ['reviews', 'accept', <slug>]", () => {
    expect(acceptArgs("ship_v1")).toEqual(["reviews", "accept", "ship_v1"]);
  });

  it("rejectArgs is ['reviews', 'reject', <slug>]", () => {
    expect(rejectArgs("ship_v1")).toEqual(["reviews", "reject", "ship_v1"]);
  });

  it("editAndRerunArgs passes --bet, --all, --reviewer-notes in order", () => {
    expect(editAndRerunArgs("ship_v1", "scope is too small")).toEqual([
      "--bet",
      "ship_v1",
      "--all",
      "--reviewer-notes",
      "scope is too small",
    ]);
  });

  it("editAndRerunArgs preserves an empty notes string verbatim", () => {
    // Empty string is a legitimate value — the skill decides what to do
    // with it. The plugin never mutates the notes payload.
    expect(editAndRerunArgs("ship_v1", "")).toEqual([
      "--bet",
      "ship_v1",
      "--all",
      "--reviewer-notes",
      "",
    ]);
  });

  it("editAndRerunArgs preserves multi-line notes verbatim", () => {
    const notes = "line one\nline two";
    expect(editAndRerunArgs("ship_v1", notes)[4]).toBe(notes);
  });
});
