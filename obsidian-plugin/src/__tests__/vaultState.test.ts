/**
 * Tests for vaultState.scan — covers the detection rules locked in
 * architecture §2.2 and the parse-error handling in §7.4.
 *
 * Each test that needs to vary frontmatter writes a tiny temp vault under
 * os.tmpdir(); the static fixture under tests/fixtures/vault is used for the
 * happy-path smoke test so the canonical layout is exercised.
 */

import { afterEach, beforeEach, describe, expect, it, MockInstance, vi } from "vitest";
import { mkdir, mkdtemp, rm, writeFile } from "fs/promises";
import { tmpdir } from "os";
import { join } from "path";

import { scan, ScanOptions } from "../vaultState";

const FIXTURE_VAULT = join(__dirname, "..", "..", "tests", "fixtures", "vault");

function defaultOpts(vaultRoot: string, overrides: Partial<ScanOptions> = {}): ScanOptions {
  return {
    vaultRoot,
    reviewsDir: "Brain/Reviews",
    conflictsFile: "Brain/CONFLICTS.md",
    betsDir: "Brain/Bets",
    staleAfterDays: 30,
    today: new Date(Date.UTC(2026, 3, 29)), // 2026-04-29
    ...overrides,
  };
}

describe("vaultState.scan — happy path against fixture vault", () => {
  it("returns expected briefs, conflicts, and stale bets", async () => {
    const state = await scan(defaultOpts(FIXTURE_VAULT));

    expect(state.pendingBriefs).toHaveLength(1);
    expect(state.pendingBriefs[0]).toMatchObject({
      betSlug: "ship_v1",
      owner: "ceo",
      proposedClosure: true,
      costUsd: 1.23,
      briefPath: "Brain/Reviews/ship_v1/brief.md",
    });

    expect(state.openConflicts).toHaveLength(1);
    expect(state.openConflicts[0]).toMatchObject({
      id: "C-2026-04-25-ship_v1",
      owner: "ceo",
      firstDetected: "2026-04-25",
      anchor: "C-2026-04-25-ship_v1",
    });
    expect(state.openConflicts[0].daysOpen).toBe(4);
    expect(state.openConflicts[0].betFile).toBe("bet_ship_v1.md");

    // bet_ship_v1 has fresh last_reviewed and specified kill_criteria → not stale.
    // bet_open_source has the sentinel → stale.
    expect(state.staleBets).toHaveLength(1);
    expect(state.staleBets[0]).toMatchObject({
      slug: "open_source",
      owner: "ceo",
      killCriteriaUnspecified: true,
    });

    expect(state.generation).toBeGreaterThan(0);
    expect(state.scannedAt).toBeGreaterThan(0);
  });
});

describe("vaultState.scan — synthetic edge cases", () => {
  let dir: string;
  // Loosened typing — vitest's MockInstance generics around console.warn
  // produce noisy type errors under strict TS that don't reflect real bugs.
  let warnSpy: MockInstance;

  beforeEach(async () => {
    dir = await mkdtemp(join(tmpdir(), "gb-vaultstate-"));
    await mkdir(join(dir, "Brain", "Bets"), { recursive: true });
    await mkdir(join(dir, "Brain", "Reviews"), { recursive: true });
    warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
  });

  afterEach(async () => {
    warnSpy.mockRestore();
    await rm(dir, { recursive: true, force: true });
  });

  it("skips files with malformed frontmatter and console.warns", async () => {
    // Valid bet so we can assert scan still completes alongside the bad file.
    await writeFile(
      join(dir, "Brain", "Bets", "bet_good.md"),
      "---\nslug: good\nowner: ceo\nstatus: active\nkill_criteria: real\nlast_reviewed: 2026-04-28\n---\n# good\n",
    );
    await writeFile(
      join(dir, "Brain", "Bets", "bet_broken.md"),
      "---\nslug: broken\nowner: ceo\nstatus: active\nkill_criteria: \"unterminated\nlast_reviewed: 2026-04-28\n",
    );

    const state = await scan(defaultOpts(dir));

    expect(warnSpy).toHaveBeenCalled();
    const warnedAboutBroken = warnSpy.mock.calls.some((call) =>
      String(call[0]).includes("bet_broken.md"),
    );
    expect(warnedAboutBroken).toBe(true);

    // Scan still completes — bet_good.md is processed (not stale today).
    expect(state.pendingBriefs).toEqual([]);
  });

  it("treats missing last_reviewed as never-reviewed → stale", async () => {
    await writeFile(
      join(dir, "Brain", "Bets", "bet_unreviewed.md"),
      "---\nslug: unreviewed\nowner: ceo\nstatus: active\nkill_criteria: \"real criterion\"\n---\n# bet\n",
    );

    const state = await scan(defaultOpts(dir));

    expect(state.staleBets).toHaveLength(1);
    expect(state.staleBets[0].slug).toBe("unreviewed");
    expect(state.staleBets[0].lastReviewed).toBe("");
    expect(state.staleBets[0].killCriteriaUnspecified).toBe(false);
  });

  it("flags kill_criteria sentinel (em-dash matters) as stale even with fresh last_reviewed", async () => {
    await writeFile(
      join(dir, "Brain", "Bets", "bet_unspecced.md"),
      "---\nslug: unspecced\nowner: ceo\nstatus: active\nkill_criteria: \"unspecified — needs sparring\"\nlast_reviewed: 2026-04-29\n---\n# bet\n",
    );

    const state = await scan(defaultOpts(dir));

    expect(state.staleBets).toHaveLength(1);
    expect(state.staleBets[0].killCriteriaUnspecified).toBe(true);
    expect(state.staleBets[0].daysSinceReview).toBe(0);
  });

  it("does NOT flag a bet whose deferred_until is in the future", async () => {
    await writeFile(
      join(dir, "Brain", "Bets", "bet_deferred.md"),
      "---\nslug: deferred\nowner: ceo\nstatus: active\nkill_criteria: \"real\"\nlast_reviewed: 2025-01-01\ndeferred_until: 2026-06-01\n---\n# bet\n",
    );

    const state = await scan(defaultOpts(dir));

    expect(state.staleBets).toEqual([]);
  });

  it("flags a bet whose deferred_until has expired (re-enters detection)", async () => {
    await writeFile(
      join(dir, "Brain", "Bets", "bet_expired.md"),
      "---\nslug: expired\nowner: ceo\nstatus: active\nkill_criteria: \"real\"\nlast_reviewed: 2026-04-29\ndeferred_until: 2026-04-28\n---\n# bet\n",
    );

    const state = await scan(defaultOpts(dir));

    expect(state.staleBets).toHaveLength(1);
    expect(state.staleBets[0].slug).toBe("expired");
  });

  it("discovers per-leader brief layout alongside flat layout", async () => {
    // Flat: Brain/Reviews/foo/brief.md
    await mkdir(join(dir, "Brain", "Reviews", "foo"), { recursive: true });
    await writeFile(
      join(dir, "Brain", "Reviews", "foo", "brief.md"),
      "---\nstatus: pending\nbet: foo\nowner: ceo\nagent_run_id: \"2026-04-29T09:00:00Z\"\n---\n# brief\n",
    );

    // Per-leader: Brain/Reviews/ceo/bar/brief.md
    await mkdir(join(dir, "Brain", "Reviews", "ceo", "bar"), { recursive: true });
    await writeFile(
      join(dir, "Brain", "Reviews", "ceo", "bar", "brief.md"),
      "---\nstatus: pending\nbet: bar\nowner: ceo\nagent_run_id: \"2026-04-29T10:00:00Z\"\n---\n# brief\n",
    );

    const state = await scan(defaultOpts(dir));

    expect(state.pendingBriefs).toHaveLength(2);
    const slugs = state.pendingBriefs.map((b) => b.betSlug);
    expect(slugs).toContain("foo");
    expect(slugs).toContain("bar");
  });

  it("sorts pendingBriefs oldest-first by agent_run_id", async () => {
    await mkdir(join(dir, "Brain", "Reviews", "newer"), { recursive: true });
    await mkdir(join(dir, "Brain", "Reviews", "oldest"), { recursive: true });
    await mkdir(join(dir, "Brain", "Reviews", "middle"), { recursive: true });

    await writeFile(
      join(dir, "Brain", "Reviews", "newer", "brief.md"),
      "---\nstatus: pending\nbet: newer\nowner: ceo\nagent_run_id: \"2026-04-29T12:00:00Z\"\n---\n",
    );
    await writeFile(
      join(dir, "Brain", "Reviews", "oldest", "brief.md"),
      "---\nstatus: pending\nbet: oldest\nowner: ceo\nagent_run_id: \"2026-04-28T08:00:00Z\"\n---\n",
    );
    await writeFile(
      join(dir, "Brain", "Reviews", "middle", "brief.md"),
      "---\nstatus: pending\nbet: middle\nowner: ceo\nagent_run_id: \"2026-04-29T08:00:00Z\"\n---\n",
    );

    const state = await scan(defaultOpts(dir));

    expect(state.pendingBriefs.map((b) => b.betSlug)).toEqual([
      "oldest",
      "middle",
      "newer",
    ]);
  });

  it("filters out non-pending briefs", async () => {
    await mkdir(join(dir, "Brain", "Reviews", "accepted"), { recursive: true });
    await writeFile(
      join(dir, "Brain", "Reviews", "accepted", "brief.md"),
      "---\nstatus: accepted\nbet: accepted\nowner: ceo\nagent_run_id: \"2026-04-28T08:00:00Z\"\n---\n",
    );

    const state = await scan(defaultOpts(dir));

    expect(state.pendingBriefs).toEqual([]);
  });

  it("returns an empty state when CONFLICTS.md is missing", async () => {
    const state = await scan(defaultOpts(dir));
    expect(state.openConflicts).toEqual([]);
  });

  it("matches conflict headings whose slug contains hyphens", async () => {
    // Real CNS pipeline IDs include hyphen-containing slugs from `cns/detector.py`:
    // e.g. `-needs-sparring`, `-killed-trigger`, `-vs-...`. Regression for the
    // regex previously rejecting hyphens in the slug suffix (PR #55 review).
    const conflictsBody = [
      "# Open Conflicts",
      "_Last updated by detector: 2026-04-29_",
      "",
      "## CEO (ceo)",
      "### C-2026-04-29-ship-v1-needs-sparring (1 day open)",
      "- **Bet:** [[bet_ship_v1]]",
      "- **First detected:** 2026-04-28",
      "- **Trigger:** Kill criteria for 'Ship v1' is unspecified — needs sparring.",
      "",
    ].join("\n");
    await writeFile(join(dir, "Brain", "CONFLICTS.md"), conflictsBody);

    const state = await scan(defaultOpts(dir));

    expect(state.openConflicts).toHaveLength(1);
    expect(state.openConflicts[0]).toMatchObject({
      id: "C-2026-04-29-ship-v1-needs-sparring",
      owner: "ceo",
      betFile: "bet_ship_v1.md",
      firstDetected: "2026-04-28",
      anchor: "C-2026-04-29-ship-v1-needs-sparring",
    });
  });

  it("does not include archived/closed bets (status != active)", async () => {
    await writeFile(
      join(dir, "Brain", "Bets", "bet_killed.md"),
      "---\nslug: killed\nowner: ceo\nstatus: killed\nkill_criteria: \"unspecified — needs sparring\"\n---\n",
    );

    const state = await scan(defaultOpts(dir));
    expect(state.staleBets).toEqual([]);
  });
});
