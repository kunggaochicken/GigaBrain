/**
 * Tests for `processors/conflictsActions`.
 *
 * The pure predicate layer is the load-bearing surface (architecture §1.1):
 * regex parsing of `### C-...` headings, bullet-list extraction of the
 * `**Bet:**` wikilink, and the bet-target fallback. Those tests run in
 * plain node.
 *
 * For the DOM-injection shape, we avoid a jsdom dependency by hand-rolling
 * a minimal Element shim with just the surface the processor reaches for
 * (querySelectorAll, nextElementSibling, insertAdjacentElement, tagName,
 * textContent, classList). This mirrors the lightweight-stub pattern in
 * `__stubs__/obsidian.ts`: only model the surface the production code
 * reaches for, leave the rest unimplemented.
 */

import {
  afterEach,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";

import {
  conflictIdSlug,
  extractBetWikilink,
  extractConflictId,
  fallbackBetTarget,
  resolveBetTarget,
} from "../processors/conflictsActions.predicates";

// ---------------------------------------------------------------------------
// Predicate tests
// ---------------------------------------------------------------------------

describe("extractConflictId", () => {
  // The vaultState-side regex was widened to include hyphens in the slug
  // (PR fix: detector emits suffixes like `-needs-sparring`). The action-bar
  // processor must stay in lockstep; pin both shapes here so a regression
  // can't slip through.
  it("matches an underscore-only slug", () => {
    expect(extractConflictId("C-2026-04-29-foo")).toBe("C-2026-04-29-foo");
  });

  it("matches a hyphen-containing slug", () => {
    expect(extractConflictId("C-2026-04-29-foo-needs-sparring")).toBe(
      "C-2026-04-29-foo-needs-sparring",
    );
  });

  it("strips the trailing parenthetical that the renderer appends", () => {
    expect(extractConflictId("C-2026-04-29-foo (3 days open)")).toBe(
      "C-2026-04-29-foo",
    );
    expect(
      extractConflictId("C-2026-04-29-foo-needs-sparring (12 days open)"),
    ).toBe("C-2026-04-29-foo-needs-sparring");
  });

  it("tolerates leading/trailing whitespace from textContent", () => {
    expect(extractConflictId("  C-2026-04-29-foo  ")).toBe("C-2026-04-29-foo");
  });

  it("returns null for non-conflict headings", () => {
    expect(extractConflictId("CTO (cto)")).toBeNull();
    expect(extractConflictId("Open Conflicts")).toBeNull();
    expect(extractConflictId("")).toBeNull();
  });

  it("rejects malformed conflict ids", () => {
    expect(extractConflictId("C-2026-4-29-foo")).toBeNull(); // single-digit month
    expect(extractConflictId("C-2026-04-29-")).toBeNull(); // empty slug
    expect(extractConflictId("C-2026-04-29-FOO")).toBeNull(); // uppercase slug
  });
});

describe("extractBetWikilink", () => {
  it("pulls the basename out of a `- **Bet:** [[bet_foo]]` line", () => {
    expect(extractBetWikilink("- **Bet:** [[bet_foo]]")).toBe("bet_foo");
  });

  it("strips a trailing .md from the wikilink target", () => {
    expect(extractBetWikilink("- **Bet:** [[bet_foo.md]]")).toBe("bet_foo");
  });

  it("tolerates a missing leading `- ` (post-render textContent)", () => {
    expect(extractBetWikilink("**Bet:** [[bet_foo]]")).toBe("bet_foo");
  });

  it("preserves hyphens in the bet basename", () => {
    expect(extractBetWikilink("- **Bet:** [[bet_open-source]]")).toBe(
      "bet_open-source",
    );
  });

  it("returns null on lines that are not a Bet line", () => {
    expect(extractBetWikilink("- **Trigger:** something")).toBeNull();
    expect(extractBetWikilink("- **First detected:** 2026-04-29")).toBeNull();
    expect(extractBetWikilink("")).toBeNull();
  });

  it("returns null on a Bet line without a wikilink", () => {
    expect(extractBetWikilink("- **Bet:** bet_foo.md")).toBeNull();
  });
});

describe("fallbackBetTarget", () => {
  it("derives `bet_<slug>` from a conflict id with underscores", () => {
    expect(fallbackBetTarget("C-2026-04-29-foo")).toBe("bet_foo");
  });

  it("derives `bet_<slug>` from a conflict id with hyphens", () => {
    expect(fallbackBetTarget("C-2026-04-29-foo-needs-sparring")).toBe(
      "bet_foo-needs-sparring",
    );
  });

  it("returns null on a non-conflict id", () => {
    expect(fallbackBetTarget("not-a-conflict")).toBeNull();
  });
});

describe("conflictIdSlug", () => {
  it("returns the slug after the date prefix", () => {
    expect(conflictIdSlug("C-2026-04-29-foo")).toBe("foo");
    expect(conflictIdSlug("C-2026-04-29-foo-bar")).toBe("foo-bar");
  });

  it("returns null on garbage", () => {
    expect(conflictIdSlug("foo")).toBeNull();
  });
});

describe("resolveBetTarget", () => {
  it("prefers the bullet-list wikilink over the fallback", () => {
    const bullets = [
      "- **First detected:** 2026-04-29",
      "- **Bet:** [[bet_explicit]]",
      "- **Trigger:** something",
    ];
    expect(resolveBetTarget("C-2026-04-29-derived", bullets)).toBe(
      "bet_explicit",
    );
  });

  it("falls back to bet_<slug> when no `**Bet:**` line is present", () => {
    const bullets = [
      "- **First detected:** 2026-04-29",
      "- **Trigger:** something",
    ];
    expect(resolveBetTarget("C-2026-04-29-foo", bullets)).toBe("bet_foo");
  });

  it("falls back across hyphenated slugs", () => {
    expect(
      resolveBetTarget("C-2026-04-29-foo-needs-sparring", []),
    ).toBe("bet_foo-needs-sparring");
  });
});

// ---------------------------------------------------------------------------
// DOM-injection shape
// ---------------------------------------------------------------------------

/**
 * Minimal Element-like fake: only the surface the processor reaches for.
 * Mirrors the obsidian-stub philosophy: don't model what isn't touched.
 *
 * - tagName, textContent, nextElementSibling, classList, children
 * - querySelectorAll(selector) — only handles two selectors:
 *     * "h3" — recursively collect descendants with tagName "h3"
 *     * ":scope > li" — direct-children that are <li>
 * - insertAdjacentElement("afterend", node) — splice into parent.children
 *   right after `this`.
 */
class FakeElement {
  tagName: string;
  children: FakeElement[] = [];
  parent: FakeElement | null = null;
  private _textContent: string;
  private _classes: Set<string> = new Set();
  classList = {
    add: (...names: string[]): void => {
      for (const n of names) this._classes.add(n);
    },
    contains: (name: string): boolean => this._classes.has(name),
  };
  attrs: Record<string, string> = {};
  events: Record<string, Array<(ev: { preventDefault: () => void }) => void>> =
    {};

  constructor(tagName: string, textContent = "") {
    this.tagName = tagName.toUpperCase();
    this._textContent = textContent;
  }

  get textContent(): string {
    if (this.children.length === 0) return this._textContent;
    return (
      this._textContent +
      this.children.map((c) => c.textContent).join("")
    );
  }

  set textContent(value: string) {
    this._textContent = value;
    this.children = [];
  }

  appendChild<T extends FakeElement>(child: T): T {
    child.parent = this;
    this.children.push(child);
    return child;
  }

  get nextElementSibling(): FakeElement | null {
    if (!this.parent) return null;
    const idx = this.parent.children.indexOf(this);
    if (idx < 0 || idx === this.parent.children.length - 1) return null;
    return this.parent.children[idx + 1];
  }

  insertAdjacentElement(
    where: "afterend" | "beforebegin" | "afterbegin" | "beforeend",
    node: FakeElement,
  ): FakeElement {
    if (where !== "afterend") {
      throw new Error(`FakeElement only models afterend; got ${where}`);
    }
    if (!this.parent) {
      throw new Error("insertAdjacentElement: detached element");
    }
    const idx = this.parent.children.indexOf(this);
    node.parent = this.parent;
    this.parent.children.splice(idx + 1, 0, node);
    return node;
  }

  querySelectorAll(selector: string): FakeElement[] {
    if (selector === "h3") {
      const out: FakeElement[] = [];
      const walk = (n: FakeElement): void => {
        for (const c of n.children) {
          if (c.tagName === "H3") out.push(c);
          walk(c);
        }
      };
      walk(this);
      return out;
    }
    if (selector === ":scope > li") {
      return this.children.filter((c) => c.tagName === "LI");
    }
    throw new Error(`FakeElement does not implement selector ${selector}`);
  }

  addEventListener(
    type: string,
    handler: (ev: { preventDefault: () => void }) => void,
  ): void {
    (this.events[type] ??= []).push(handler);
  }
}

function makeDocumentStub() {
  return {
    createElement: (tag: string): FakeElement => new FakeElement(tag),
    createTextNode: (text: string): FakeElement => {
      const node = new FakeElement("#text", text);
      return node;
    },
  };
}

describe("conflictsActionBar DOM injection", () => {
  let originalDocument: unknown;

  beforeEach(() => {
    originalDocument = (globalThis as { document?: unknown }).document;
    (globalThis as { document?: unknown }).document = makeDocumentStub();
  });

  afterEach(() => {
    (globalThis as { document?: unknown }).document = originalDocument;
  });

  /**
   * Build a minimal CONFLICTS.md DOM:
   *
   *   <root>
   *     <h2>CTO (cto)</h2>
   *     <h3>C-2026-04-29-foo (3 days open)</h3>
   *     <ul>
   *       <li>**First detected:** 2026-04-29</li>
   *       <li>**Bet:** [[bet_foo]]</li>
   *       <li>**Trigger:** something</li>
   *     </ul>
   *     <h3>C-2026-04-29-bar (1 day open)</h3>
   *     <ul>
   *       <li>**First detected:** 2026-04-29</li>
   *       <li>**Trigger:** something else</li>
   *     </ul>
   *   </root>
   */
  function buildFixture(): FakeElement {
    const root = new FakeElement("div");
    root.appendChild(new FakeElement("h2", "CTO (cto)"));

    const h3a = new FakeElement("h3", "C-2026-04-29-foo (3 days open)");
    root.appendChild(h3a);
    const ul1 = new FakeElement("ul");
    root.appendChild(ul1);
    ul1.appendChild(new FakeElement("li", "**First detected:** 2026-04-29"));
    ul1.appendChild(new FakeElement("li", "**Bet:** [[bet_foo]]"));
    ul1.appendChild(new FakeElement("li", "**Trigger:** something"));

    const h3b = new FakeElement("h3", "C-2026-04-29-bar (1 day open)");
    root.appendChild(h3b);
    const ul2 = new FakeElement("ul");
    root.appendChild(ul2);
    ul2.appendChild(new FakeElement("li", "**First detected:** 2026-04-29"));
    ul2.appendChild(new FakeElement("li", "**Trigger:** something else"));

    return root;
  }

  // The processor pulls in obsidian via `setIcon`/`Notice`; tests rely on
  // the existing __stubs__/obsidian.ts (mapped via vitest.config.ts) so
  // those imports resolve to no-ops. We only assert structural shape.
  async function loadProcessor() {
    return await import("../processors/conflictsActions");
  }

  function makePlugin(conflictsFile: string) {
    return {
      settings: { conflictsFile },
      app: {
        // openLinkText is wired to a spy on the plugin so we can assert
        // that the [Open bet] click reaches the workspace with the right
        // target. Ditto vault.adapter for the modal helper, but we don't
        // click [Spar this] in the structural tests.
        workspace: {
          openLinkText: vi.fn(),
        },
        vault: { adapter: null },
      },
    };
  }

  it("injects a bar after each `### C-...` heading", async () => {
    const { conflictsActionBar } = await loadProcessor();
    const root = buildFixture();
    const ctx = { sourcePath: "Brain/CONFLICTS.md" };

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    conflictsActionBar(root as any, ctx as any, makePlugin("Brain/CONFLICTS.md") as any);

    // Two conflict headings, each followed by a bar (then the original ul).
    const h3s = root.children.filter((c) => c.tagName === "H3");
    expect(h3s).toHaveLength(2);

    for (const h3 of h3s) {
      const next = h3.nextElementSibling;
      expect(next).not.toBeNull();
      expect(next!.classList.contains("gigabrain-action-bar")).toBe(true);
      // Two buttons: [Spar this], [Open bet].
      const buttons = next!.children.filter((c) => c.tagName === "BUTTON");
      expect(buttons).toHaveLength(2);
      expect(buttons[0].textContent).toContain("Spar this");
      expect(buttons[1].textContent).toContain("Open bet");
    }
  });

  it("[Open bet] click fires openLinkText with the bullet's wikilink target", async () => {
    const { conflictsActionBar } = await loadProcessor();
    const root = buildFixture();
    const ctx = { sourcePath: "Brain/CONFLICTS.md" };
    const plugin = makePlugin("Brain/CONFLICTS.md");

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    conflictsActionBar(root as any, ctx as any, plugin as any);

    // First heading is C-2026-04-29-foo with `[[bet_foo]]` in its bullets.
    const firstH3 = root.children.filter((c) => c.tagName === "H3")[0];
    const firstBar = firstH3.nextElementSibling!;
    const openBetBtn = firstBar.children.find((c) =>
      c.textContent.includes("Open bet"),
    )!;

    // Fire the click handler.
    for (const handler of openBetBtn.events.click ?? []) {
      handler({ preventDefault: () => undefined });
    }

    expect(plugin.app.workspace.openLinkText).toHaveBeenCalledTimes(1);
    expect(plugin.app.workspace.openLinkText).toHaveBeenCalledWith(
      "bet_foo",
      "Brain/CONFLICTS.md",
      true,
    );
  });

  it("[Open bet] falls back to `bet_<slug>` when no Bet bullet is present", async () => {
    const { conflictsActionBar } = await loadProcessor();
    const root = buildFixture();
    const ctx = { sourcePath: "Brain/CONFLICTS.md" };
    const plugin = makePlugin("Brain/CONFLICTS.md");

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    conflictsActionBar(root as any, ctx as any, plugin as any);

    // Second heading is C-2026-04-29-bar with NO Bet bullet — fallback.
    const secondH3 = root.children.filter((c) => c.tagName === "H3")[1];
    const secondBar = secondH3.nextElementSibling!;
    const openBetBtn = secondBar.children.find((c) =>
      c.textContent.includes("Open bet"),
    )!;

    for (const handler of openBetBtn.events.click ?? []) {
      handler({ preventDefault: () => undefined });
    }

    expect(plugin.app.workspace.openLinkText).toHaveBeenCalledWith(
      "bet_bar",
      "Brain/CONFLICTS.md",
      true,
    );
  });

  it("does not inject anything when sourcePath is not the conflicts file", async () => {
    const { conflictsActionBar } = await loadProcessor();
    const root = buildFixture();
    const ctx = { sourcePath: "Brain/SomethingElse.md" };

    const childCountBefore = root.children.length;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    conflictsActionBar(root as any, ctx as any, makePlugin("Brain/CONFLICTS.md") as any);
    expect(root.children.length).toBe(childCountBefore);
  });

  it("does not double-inject when the post-processor runs twice", async () => {
    const { conflictsActionBar } = await loadProcessor();
    const root = buildFixture();
    const ctx = { sourcePath: "Brain/CONFLICTS.md" };
    const plugin = makePlugin("Brain/CONFLICTS.md");

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    conflictsActionBar(root as any, ctx as any, plugin as any);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    conflictsActionBar(root as any, ctx as any, plugin as any);

    // Each h3 still has exactly one .gigabrain-action-bar following it.
    for (const h3 of root.children.filter((c) => c.tagName === "H3")) {
      const next = h3.nextElementSibling!;
      expect(next.classList.contains("gigabrain-action-bar")).toBe(true);
      // The element after the bar should NOT be another bar (it's the ul or
      // next h3).
      const afterBar = next.nextElementSibling;
      expect(
        afterBar?.classList.contains("gigabrain-action-bar") ?? false,
      ).toBe(false);
    }
  });

  it("ignores h3s whose text is not a conflict id", async () => {
    const { conflictsActionBar } = await loadProcessor();
    const root = new FakeElement("div");
    const noise = new FakeElement("h3", "Some other heading");
    root.appendChild(noise);
    const ctx = { sourcePath: "Brain/CONFLICTS.md" };

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    conflictsActionBar(root as any, ctx as any, makePlugin("Brain/CONFLICTS.md") as any);

    expect(noise.nextElementSibling).toBeNull();
  });
});
