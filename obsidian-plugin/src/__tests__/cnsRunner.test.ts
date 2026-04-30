/**
 * Tests for cnsRunner.discoverBinary — covers the documented resolution order:
 *   1. settings override
 *   2. ~/.local/bin/cns
 *   3. `which cns` on PATH
 *   4. throw with actionable message
 */

import { describe, expect, it, vi } from "vitest";
import { join } from "path";

import { CnsBinaryNotFoundError, discoverBinary } from "../cnsRunner";

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
