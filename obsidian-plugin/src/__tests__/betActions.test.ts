/**
 * Tests for `processors/betActions` — pure-logic surface only.
 *
 * Modal + DOM rendering are explicitly hard-to-test (architecture §5.2);
 * we cover them by hand. These tests pin the slug derivation and the
 * trigger predicate, which are the load-bearing decisions.
 */

import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";

import {
  deriveSlug,
  isFirstSection,
  shouldInjectBar,
} from "../processors/betActions.predicates";

describe("deriveSlug", () => {
  it("strips bet_ prefix and .md extension", () => {
    expect(deriveSlug("bet_ship_v1.md")).toBe("ship_v1");
  });

  it("preserves hyphens in slug", () => {
    expect(deriveSlug("bet_open-source.md")).toBe("open-source");
  });

  it("returns null when filename does not match the bet_*.md shape", () => {
    expect(deriveSlug("README.md")).toBeNull();
    expect(deriveSlug("bet_.md")).toBeNull();
    expect(deriveSlug("bet_x.txt")).toBeNull();
    expect(deriveSlug("not_a_bet.md")).toBeNull();
  });
});

describe("shouldInjectBar", () => {
  const BETS_DIR = "Brain/Bets";
  const validFrontmatter = `---
status: active
owner: ceo
---

body
`;

  it("returns true for bet_*.md under the bets dir with status frontmatter", () => {
    expect(
      shouldInjectBar(
        "Brain/Bets/bet_ship_v1.md",
        validFrontmatter,
        BETS_DIR,
      ),
    ).toBe(true);
  });

  it("returns true under nested subdirs of the bets dir", () => {
    expect(
      shouldInjectBar(
        "Brain/Bets/sub/bet_x.md",
        validFrontmatter,
        BETS_DIR,
      ),
    ).toBe(true);
  });

  it("returns false when path is outside the bets dir", () => {
    expect(
      shouldInjectBar(
        "Brain/Reviews/bet_ship_v1.md",
        validFrontmatter,
        BETS_DIR,
      ),
    ).toBe(false);
  });

  it("returns false when filename does not match bet_*.md", () => {
    expect(
      shouldInjectBar(
        "Brain/Bets/BETS.md",
        validFrontmatter,
        BETS_DIR,
      ),
    ).toBe(false);
  });

  it("returns false when frontmatter has no status field", () => {
    const noStatus = `---
owner: ceo
---

body
`;
    expect(
      shouldInjectBar(
        "Brain/Bets/bet_x.md",
        noStatus,
        BETS_DIR,
      ),
    ).toBe(false);
  });

  it("returns false when frontmatter is absent entirely", () => {
    expect(
      shouldInjectBar(
        "Brain/Bets/bet_x.md",
        "no frontmatter here",
        BETS_DIR,
      ),
    ).toBe(false);
  });

  describe("frontmatter parse failure path", () => {
    // Typed as `any` here because vitest's `vi.spyOn` return type does not
    // narrow to a console-method spy without extra ceremony, and this is
    // a test-only handle.
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
      // Unbalanced quotes inside the frontmatter block trip gray-matter.
      const broken = `---
status: "unterminated
owner: ceo
---

body
`;
      const result = shouldInjectBar(
        "Brain/Bets/bet_x.md",
        broken,
        BETS_DIR,
      );

      expect(result).toBe(false);
      expect(warnSpy).toHaveBeenCalledOnce();
      expect(warnSpy.mock.calls[0][0]).toMatch(/frontmatter parse failed/);
    });
  });

  it("respects a custom betsDir setting", () => {
    expect(
      shouldInjectBar(
        "MyVault/Strategy/bet_thing.md",
        validFrontmatter,
        "MyVault/Strategy",
      ),
    ).toBe(true);

    expect(
      shouldInjectBar(
        "Brain/Bets/bet_thing.md",
        validFrontmatter,
        "MyVault/Strategy",
      ),
    ).toBe(false);
  });

  it("normalizes a trailing slash on betsDir", () => {
    expect(
      shouldInjectBar(
        "Brain/Bets/bet_x.md",
        validFrontmatter,
        "Brain/Bets/",
      ),
    ).toBe(true);
  });
});

describe("isFirstSection", () => {
  // The post-processor runs once per rendered preview section. The bar
  // belongs only on the section anchored at the file's first line; every
  // other section short-circuits. This pins the predicate that drives that
  // decision (PR #56 review: "inject the action bar only once per note").
  it("returns true when the section starts at the top of the file", () => {
    expect(isFirstSection({ lineStart: 0 })).toBe(true);
  });

  it("returns false for any later section", () => {
    expect(isFirstSection({ lineStart: 5 })).toBe(false);
    expect(isFirstSection({ lineStart: 1 })).toBe(false);
  });

  it("returns false when the section info is null or undefined", () => {
    expect(isFirstSection(null)).toBe(false);
    expect(isFirstSection(undefined)).toBe(false);
  });
});
