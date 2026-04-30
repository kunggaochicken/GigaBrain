/**
 * Tests for `watchers/betWatcher` — the Phase 4 / GIG-102 auto-reindex
 * watcher. Architecture §2.3 / §7.5 lock the contract:
 *
 *   - Trigger only on modify events under `<betsDir>/bet_*.md`.
 *   - Debounce 1500ms (cancel-and-reset).
 *   - Run `cns reindex --check`; exit-zero short-circuits.
 *   - Non-zero `--check` triggers `cns reindex`.
 *   - Surface result/failure via Notice (stderr first non-empty line).
 *   - On dispose: cancel timer + AbortSignal-abort in-flight reindex.
 *
 * The cnsRunner is dependency-injected; we never spawn real processes here.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  BetWatcher,
  DEFAULT_REINDEX_DEBOUNCE_MS,
  isBetFilePath,
} from "../watchers/betWatcher";
import type { RunResult } from "../cnsRunner";

interface RunCall {
  bin: string;
  args: string[];
  cwd?: string;
  signal?: AbortSignal;
  timeoutMs?: number;
}

/**
 * Shared test scaffold: a programmable runner that records calls and resolves
 * with whatever `RunResult` queue the test sets up. Each call shifts one
 * result off the queue; if the queue is empty we resolve to a benign exit-0
 * so misconfigured tests fail loudly via assertion (not via hang).
 */
function makeRunner(results: RunResult[]) {
  const calls: RunCall[] = [];
  const queue = [...results];
  const runner = vi.fn(
    async (
      bin: string,
      args: string[],
      opts: { cwd?: string; signal?: AbortSignal; timeoutMs?: number },
    ): Promise<RunResult> => {
      calls.push({ bin, args, cwd: opts.cwd, signal: opts.signal, timeoutMs: opts.timeoutMs });
      return (
        queue.shift() ?? {
          stdout: "",
          stderr: "no result configured",
          code: 0,
        }
      );
    },
  );
  return { runner, calls };
}

const BIN = "/usr/local/bin/cns";
const VAULT = "/vault";
const BETS_DIR = "Brain/Bets";

function makeHost(opts: {
  runner: ReturnType<typeof makeRunner>["runner"];
  notices?: Array<{ message: string; timeout?: number }>;
  betsDir?: string;
  debounceMs?: number;
  cnsBinaryPath?: string | null;
  vaultRoot?: string | null;
}) {
  const notices = opts.notices ?? [];
  return {
    cnsBinaryPath:
      "cnsBinaryPath" in opts ? opts.cnsBinaryPath ?? null : BIN,
    vaultRoot: "vaultRoot" in opts ? opts.vaultRoot ?? null : VAULT,
    getBetsDir: () => opts.betsDir ?? BETS_DIR,
    getDebounceMs: () => opts.debounceMs ?? DEFAULT_REINDEX_DEBOUNCE_MS,
    runner: opts.runner,
    noticeFn: (message: string, timeout?: number) => {
      notices.push({ message, timeout });
    },
  };
}

describe("isBetFilePath", () => {
  it("matches direct children matching bet_*.md", () => {
    expect(isBetFilePath("Brain/Bets/bet_x.md", BETS_DIR)).toBe(true);
    expect(isBetFilePath("Brain/Bets/bet_ship_v1.md", BETS_DIR)).toBe(true);
    expect(isBetFilePath("Brain/Bets/bet_open-source.md", BETS_DIR)).toBe(true);
  });

  it("rejects paths outside the bets dir", () => {
    expect(isBetFilePath("Brain/Reviews/bet_x.md", BETS_DIR)).toBe(false);
    expect(isBetFilePath("OtherDir/bet_x.md", BETS_DIR)).toBe(false);
  });

  it("rejects nested children of the bets dir", () => {
    // Architecture §2.3 scopes the watcher to direct `<betsDir>/bet_*.md`.
    expect(isBetFilePath("Brain/Bets/sub/bet_x.md", BETS_DIR)).toBe(false);
  });

  it("rejects non-bet markdown files in the bets dir", () => {
    expect(isBetFilePath("Brain/Bets/BETS.md", BETS_DIR)).toBe(false);
    expect(isBetFilePath("Brain/Bets/README.md", BETS_DIR)).toBe(false);
    expect(isBetFilePath("Brain/Bets/notbet.md", BETS_DIR)).toBe(false);
  });

  it("rejects non-markdown bet-prefixed files", () => {
    expect(isBetFilePath("Brain/Bets/bet_x.txt", BETS_DIR)).toBe(false);
  });

  it("normalizes a trailing slash on betsDir", () => {
    expect(isBetFilePath("Brain/Bets/bet_x.md", "Brain/Bets/")).toBe(true);
  });

  it("respects a custom betsDir", () => {
    expect(isBetFilePath("MyVault/Strategy/bet_x.md", "MyVault/Strategy")).toBe(
      true,
    );
  });
});

describe("BetWatcher", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("ignores modifies for paths outside <betsDir>/bet_*.md", async () => {
    const { runner, calls } = makeRunner([]);
    const host = makeHost({ runner });
    const watcher = new BetWatcher(host);

    watcher.handleModify("Brain/Reviews/foo/brief.md");
    watcher.handleModify("Brain/CONFLICTS.md");
    watcher.handleModify("Brain/Bets/BETS.md");
    watcher.handleModify("Brain/Bets/sub/bet_x.md");

    await vi.advanceTimersByTimeAsync(DEFAULT_REINDEX_DEBOUNCE_MS + 100);

    expect(calls).toHaveLength(0);
    expect(runner).not.toHaveBeenCalled();
  });

  it("coalesces multiple rapid modifies into a single reindex run", async () => {
    const { runner, calls } = makeRunner([
      // --check returns non-zero so we proceed to a full reindex.
      { stdout: "", stderr: "", code: 1 },
      // reindex returns success.
      { stdout: "ok", stderr: "", code: 0 },
    ]);
    const host = makeHost({ runner });
    const watcher = new BetWatcher(host);

    // Fire 5 rapid modifies, each within the debounce window.
    for (let i = 0; i < 5; i += 1) {
      watcher.handleModify("Brain/Bets/bet_x.md");
      await vi.advanceTimersByTimeAsync(200);
    }
    // Now let the debounce settle.
    await vi.advanceTimersByTimeAsync(DEFAULT_REINDEX_DEBOUNCE_MS + 100);
    // Allow the queued microtasks (await runner, await runner) to drain.
    await vi.runAllTimersAsync();

    // Exactly one --check + one reindex, not five.
    expect(calls).toHaveLength(2);
    expect(calls[0]).toMatchObject({
      bin: BIN,
      args: ["reindex", "--check"],
      cwd: VAULT,
    });
    expect(calls[1]).toMatchObject({
      bin: BIN,
      args: ["reindex"],
      cwd: VAULT,
    });
  });

  it("short-circuits when `reindex --check` exits 0 (no work needed)", async () => {
    const { runner, calls } = makeRunner([
      { stdout: "", stderr: "", code: 0 },
    ]);
    const notices: Array<{ message: string; timeout?: number }> = [];
    const host = makeHost({ runner, notices });
    const watcher = new BetWatcher(host);

    watcher.handleModify("Brain/Bets/bet_x.md");
    await vi.advanceTimersByTimeAsync(DEFAULT_REINDEX_DEBOUNCE_MS + 100);
    await vi.runAllTimersAsync();

    expect(calls).toHaveLength(1);
    expect(calls[0].args).toEqual(["reindex", "--check"]);
    // No reindex follow-up.
    expect(runner).toHaveBeenCalledTimes(1);
    // No user-facing Notice when nothing changed (architecture §2.3 short-
    // circuit "we only pay the reindex cost when a bet truly changed").
    expect(notices).toHaveLength(0);
  });

  it("runs `reindex` and shows success Notice when --check is non-zero", async () => {
    const { runner, calls } = makeRunner([
      { stdout: "needs reindex", stderr: "", code: 1 },
      { stdout: "rebuilt", stderr: "", code: 0 },
    ]);
    const notices: Array<{ message: string; timeout?: number }> = [];
    const host = makeHost({ runner, notices });
    const watcher = new BetWatcher(host);

    watcher.handleModify("Brain/Bets/bet_x.md");
    await vi.advanceTimersByTimeAsync(DEFAULT_REINDEX_DEBOUNCE_MS + 100);
    await vi.runAllTimersAsync();

    expect(calls).toHaveLength(2);
    expect(calls[1].args).toEqual(["reindex"]);
    expect(notices).toHaveLength(1);
    expect(notices[0].message).toBe("GigaBrain: reindex done");
  });

  it("surfaces stderr verbatim on reindex failure", async () => {
    const { runner } = makeRunner([
      { stdout: "", stderr: "", code: 1 },
      { stdout: "", stderr: "boom: stale lockfile\nstacktrace…", code: 2 },
    ]);
    const notices: Array<{ message: string; timeout?: number }> = [];
    const host = makeHost({ runner, notices });
    const watcher = new BetWatcher(host);

    watcher.handleModify("Brain/Bets/bet_x.md");
    await vi.advanceTimersByTimeAsync(DEFAULT_REINDEX_DEBOUNCE_MS + 100);
    await vi.runAllTimersAsync();

    expect(notices).toHaveLength(1);
    expect(notices[0].message).toBe(
      "GigaBrain: reindex failed: boom: stale lockfile",
    );
  });

  it("respects a settings-overridden debounce window", async () => {
    const { runner, calls } = makeRunner([
      { stdout: "", stderr: "", code: 0 },
    ]);
    const host = makeHost({ runner, debounceMs: 3000 });
    const watcher = new BetWatcher(host);

    watcher.handleModify("Brain/Bets/bet_x.md");

    // 1500ms (default) — still nothing, because user raised it to 3000.
    await vi.advanceTimersByTimeAsync(1500);
    expect(calls).toHaveLength(0);

    await vi.advanceTimersByTimeAsync(1600);
    await vi.runAllTimersAsync();
    expect(calls).toHaveLength(1);
  });

  it("skips when cns binary or vault root is unresolved", async () => {
    const { runner, calls } = makeRunner([]);
    const host = makeHost({ runner, cnsBinaryPath: null });
    const watcher = new BetWatcher(host);

    watcher.handleModify("Brain/Bets/bet_x.md");
    await vi.advanceTimersByTimeAsync(DEFAULT_REINDEX_DEBOUNCE_MS + 100);
    await vi.runAllTimersAsync();

    expect(calls).toHaveLength(0);
  });

  it("dispose() cancels a pending debounce timer", async () => {
    const { runner, calls } = makeRunner([
      { stdout: "", stderr: "", code: 0 },
    ]);
    const host = makeHost({ runner });
    const watcher = new BetWatcher(host);

    watcher.handleModify("Brain/Bets/bet_x.md");
    // Don't let the timer fire — dispose first.
    await vi.advanceTimersByTimeAsync(500);
    watcher.dispose();
    await vi.advanceTimersByTimeAsync(DEFAULT_REINDEX_DEBOUNCE_MS + 100);
    await vi.runAllTimersAsync();

    expect(calls).toHaveLength(0);
  });

  it("dispose() aborts an in-flight reindex via AbortSignal", async () => {
    let capturedSignal: AbortSignal | undefined;
    // Hold the runner's pending resolver in a single-element tuple so TS's
    // control-flow analysis doesn't narrow it to `null` after the initial
    // assignment — we want to call it later from outside the executor.
    const resolverBox: { fn: ((r: RunResult) => void) | null } = { fn: null };
    const runner = vi.fn(
      async (
        _bin: string,
        _args: string[],
        opts: { signal?: AbortSignal },
      ) => {
        capturedSignal = opts.signal;
        return await new Promise<RunResult>((resolve) => {
          resolverBox.fn = resolve;
        });
      },
    );
    const host = makeHost({ runner });
    const watcher = new BetWatcher(host);

    watcher.handleModify("Brain/Bets/bet_x.md");
    await vi.advanceTimersByTimeAsync(DEFAULT_REINDEX_DEBOUNCE_MS + 100);
    // Yield to the awaited runner promise.
    await Promise.resolve();

    expect(runner).toHaveBeenCalledTimes(1);
    expect(capturedSignal).toBeDefined();
    expect(capturedSignal?.aborted).toBe(false);

    watcher.dispose();
    expect(capturedSignal?.aborted).toBe(true);

    // Resolve the hung runner promise so vitest doesn't complain about
    // dangling tasks; the watcher should swallow the result silently
    // because `disposed` is set.
    resolverBox.fn?.({ stdout: "", stderr: "", code: 0 });
    await vi.runAllTimersAsync();
  });

  it("ignores modify events after dispose", async () => {
    const { runner, calls } = makeRunner([]);
    const host = makeHost({ runner });
    const watcher = new BetWatcher(host);

    watcher.dispose();
    watcher.handleModify("Brain/Bets/bet_x.md");
    await vi.advanceTimersByTimeAsync(DEFAULT_REINDEX_DEBOUNCE_MS + 100);
    await vi.runAllTimersAsync();

    expect(calls).toHaveLength(0);
  });
});
