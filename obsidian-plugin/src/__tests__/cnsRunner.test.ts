/**
 * Tests for cnsRunner.discoverBinary — covers the documented resolution order:
 *   1. settings override
 *   2. ~/.local/bin/cns
 *   3. `which cns` on PATH
 *   4. throw with actionable message
 *
 * Also pins the AbortSignal -> child.kill("SIGTERM") wiring in `run()`
 * (regression for PR #61: dispose() during an in-flight `cns reindex`).
 */

import { describe, expect, it, vi } from "vitest";
import { EventEmitter } from "events";
import { join } from "path";

import { CnsBinaryNotFoundError, discoverBinary, run } from "../cnsRunner";

// Mock child_process.spawn for the run() regression test below. The
// discoverBinary tests above don't touch spawn, so this mock is inert for
// them.
vi.mock("child_process", () => {
  return {
    spawn: vi.fn(),
  };
});
import { spawn } from "child_process";

const HOME = "/home/leader";
const LOCAL_BIN = join(HOME, ".local", "bin", "cns");
const PATH_BIN = "/usr/local/bin/cns";
const OVERRIDE_BIN = "/opt/cns/bin/cns";

function makeDeps(opts: {
  executable: Set<string>;
  whichResult?: string | null;
}) {
  return {
    isExecutable: vi.fn(async (p: string) => opts.executable.has(p)),
    which: vi.fn(async () => opts.whichResult ?? null),
    home: () => HOME,
  };
}

describe("discoverBinary", () => {
  it("uses the explicit override when it is executable", async () => {
    const deps = makeDeps({
      executable: new Set([OVERRIDE_BIN, LOCAL_BIN, PATH_BIN]),
      whichResult: PATH_BIN,
    });

    const result = await discoverBinary(OVERRIDE_BIN, deps);

    expect(result).toBe(OVERRIDE_BIN);
    // ~/.local/bin and `which` must not be consulted when override hits.
    expect(deps.which).not.toHaveBeenCalled();
  });

  it("falls through to ~/.local/bin/cns when override is missing", async () => {
    const deps = makeDeps({
      executable: new Set([LOCAL_BIN]),
      whichResult: PATH_BIN,
    });

    const result = await discoverBinary("", deps);

    expect(result).toBe(LOCAL_BIN);
    expect(deps.which).not.toHaveBeenCalled();
  });

  it("falls through to ~/.local/bin/cns when override path is not executable", async () => {
    const deps = makeDeps({
      executable: new Set([LOCAL_BIN]),
      whichResult: PATH_BIN,
    });

    const result = await discoverBinary("/does/not/exist", deps);

    expect(result).toBe(LOCAL_BIN);
  });

  it("falls through to `which cns` when neither override nor ~/.local/bin/cns exist", async () => {
    const deps = makeDeps({
      executable: new Set(),
      whichResult: PATH_BIN,
    });

    const result = await discoverBinary("", deps);

    expect(result).toBe(PATH_BIN);
    expect(deps.which).toHaveBeenCalledOnce();
  });

  it("throws CnsBinaryNotFoundError with all tried paths when nothing resolves", async () => {
    const deps = makeDeps({
      executable: new Set(),
      whichResult: null,
    });

    const promise = discoverBinary("/explicit/path", deps);

    await expect(promise).rejects.toThrow(CnsBinaryNotFoundError);
    await expect(promise).rejects.toThrow(/\/explicit\/path/);
    await expect(promise).rejects.toThrow(/\.local\/bin\/cns/);
    await expect(promise).rejects.toThrow(/which cns/);
    await expect(promise).rejects.toThrow(/pip install/);
  });

  it("treats whitespace-only override as absent", async () => {
    const deps = makeDeps({
      executable: new Set([LOCAL_BIN]),
      whichResult: PATH_BIN,
    });

    const result = await discoverBinary("   ", deps);

    expect(result).toBe(LOCAL_BIN);
  });
});

/**
 * Minimal fake of `child_process.ChildProcessWithoutNullStreams` that
 * `run()` can attach handlers to. Mirrors the FakeChild in bridge.test.ts
 * but kept local so the two test files stay independent.
 */
class FakeChild extends EventEmitter {
  stdout = new EventEmitter();
  stderr = new EventEmitter();
  killed = false;
  killSignal: NodeJS.Signals | number | undefined;

  kill(signal?: NodeJS.Signals | number): boolean {
    this.killed = true;
    this.killSignal = signal;
    return true;
  }

  close(code: number | null): void {
    this.emit("close", code);
  }
}

describe("run", () => {
  it("kills the spawned child with SIGTERM when opts.signal aborts mid-flight", async () => {
    const child = new FakeChild();
    (spawn as unknown as ReturnType<typeof vi.fn>).mockReturnValueOnce(child);

    const ac = new AbortController();
    // timeoutMs is large so it cannot be the source of the kill — we want to
    // pin that it's the abort path that fires SIGTERM.
    const promise = run("/fake/cns", ["reindex"], {
      cwd: "/vault",
      signal: ac.signal,
      timeoutMs: 60_000,
    });

    // Give the promise body a tick to register listeners on `child`.
    await Promise.resolve();

    expect(child.killed).toBe(false);

    ac.abort();

    expect(child.killed).toBe(true);
    expect(child.killSignal).toBe("SIGTERM");

    // Simulate the OS reaping the process so the promise resolves and we
    // don't leave a dangling promise across tests.
    child.close(143);
    const result = await promise;
    // 143 = 128 + SIGTERM(15); pin a non-success exit shape so the regression
    // is enforced even if a future refactor changes the exact signal handling.
    expect(result.code).not.toBe(0);
  });
});
