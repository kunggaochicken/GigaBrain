/**
 * Tests for `bridge/claudeCode.runSkill`.
 *
 * The shell-out path is the only backend in Phases 2-4 (architecture §4.1).
 * These tests pin the spawn arguments, line-buffering behavior, exit-code
 * surfacing, and AbortSignal -> child.kill() wiring.
 *
 * Sentinel detection (Phase 5 / GIG-103) is explicitly out of scope here.
 */

import { describe, expect, it, vi } from "vitest";
import { EventEmitter } from "events";

import { runSkill, type BridgeChunk } from "../bridge/claudeCode";

/**
 * A minimal fake of `child_process.ChildProcessWithoutNullStreams` that the
 * runSkill driver can attach handlers to. We expose helper methods to
 * simulate stdout/stderr writes, error events, and process close.
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

  emitStdout(s: string): void {
    this.stdout.emit("data", Buffer.from(s, "utf8"));
  }
  emitStderr(s: string): void {
    this.stderr.emit("data", Buffer.from(s, "utf8"));
  }
  close(code: number | null): void {
    this.emit("close", code);
  }
}

function makeSpawn(child: FakeChild) {
  // Cast through unknown so we can inject the fake without modeling the full
  // overload set of node's spawn. Tests only assert call signatures.
  return vi.fn(() => child) as unknown as typeof import("child_process").spawn;
}

async function collect(it: AsyncIterable<BridgeChunk>): Promise<BridgeChunk[]> {
  const out: BridgeChunk[] = [];
  for await (const chunk of it) {
    out.push(chunk);
  }
  return out;
}

describe("runSkill", () => {
  it("invokes claude with the canonical argv shape and honors cwd", async () => {
    const child = new FakeChild();
    const spawnFn = makeSpawn(child);

    const iter = runSkill(
      "execute",
      ["--bet", "ship_v1"],
      { cwd: "/vault/root" },
      { spawn: spawnFn },
    );

    // Kick the iterator so the spawn is observed before we close.
    const consumer = collect(iter);

    // Need a microtask hop so the generator body runs to the spawn call.
    await Promise.resolve();

    expect(spawnFn).toHaveBeenCalledTimes(1);
    const callArgs = (spawnFn as unknown as ReturnType<typeof vi.fn>).mock
      .calls[0];
    expect(callArgs[0]).toBe("claude");
    expect(callArgs[1]).toEqual(["code", "-p", "/execute", "--bet", "ship_v1"]);
    expect(callArgs[2]).toMatchObject({ cwd: "/vault/root" });

    child.close(0);
    await consumer;
  });

  it("yields stdout lines as {stream:'stdout', line} chunks", async () => {
    const child = new FakeChild();
    const iter = runSkill(
      "spar",
      [],
      { cwd: "/vault" },
      { spawn: makeSpawn(child) },
    );

    const consumer = collect(iter);
    await Promise.resolve();

    child.emitStdout("hello\nworld\n");
    child.emitStdout("partial");
    child.emitStdout("-tail\n");
    child.close(0);

    const chunks = await consumer;
    expect(chunks).toEqual([
      { stream: "stdout", line: "hello" },
      { stream: "stdout", line: "world" },
      { stream: "stdout", line: "partial-tail" },
      { done: true, exitCode: 0 },
    ]);
  });

  it("yields stderr lines as {stream:'stderr', line} chunks", async () => {
    const child = new FakeChild();
    const iter = runSkill(
      "execute",
      [],
      { cwd: "/vault" },
      { spawn: makeSpawn(child) },
    );
    const consumer = collect(iter);
    await Promise.resolve();

    child.emitStderr("warn: thing\nerr: stuff\n");
    child.close(2);

    const chunks = await consumer;
    expect(chunks).toEqual([
      { stream: "stderr", line: "warn: thing" },
      { stream: "stderr", line: "err: stuff" },
      { done: true, exitCode: 2 },
    ]);
  });

  it("flushes a trailing partial line (no terminating newline) on close", async () => {
    const child = new FakeChild();
    const iter = runSkill(
      "execute",
      [],
      { cwd: "/vault" },
      { spawn: makeSpawn(child) },
    );
    const consumer = collect(iter);
    await Promise.resolve();

    child.emitStdout("no-newline-here");
    child.close(0);

    const chunks = await consumer;
    expect(chunks).toEqual([
      { stream: "stdout", line: "no-newline-here" },
      { done: true, exitCode: 0 },
    ]);
  });

  it("ends with {done: true, exitCode} carrying the non-zero exit", async () => {
    const child = new FakeChild();
    const iter = runSkill(
      "execute",
      [],
      { cwd: "/vault" },
      { spawn: makeSpawn(child) },
    );
    const consumer = collect(iter);
    await Promise.resolve();

    child.close(137);

    const chunks = await consumer;
    expect(chunks[chunks.length - 1]).toEqual({ done: true, exitCode: 137 });
  });

  it("kills the child when AbortSignal fires", async () => {
    const child = new FakeChild();
    const ac = new AbortController();
    const iter = runSkill(
      "execute",
      [],
      { cwd: "/vault", signal: ac.signal },
      { spawn: makeSpawn(child) },
    );
    const consumer = collect(iter);
    await Promise.resolve();

    ac.abort();
    expect(child.killed).toBe(true);
    expect(child.killSignal).toBe("SIGTERM");

    child.close(143);
    await consumer;
  });

  it("kills immediately when the signal is already aborted at call time", async () => {
    const child = new FakeChild();
    const ac = new AbortController();
    ac.abort();

    const iter = runSkill(
      "execute",
      [],
      { cwd: "/vault", signal: ac.signal },
      { spawn: makeSpawn(child) },
    );
    const consumer = collect(iter);
    await Promise.resolve();

    expect(child.killed).toBe(true);

    child.close(143);
    await consumer;
  });
});
