// TODO(Phase 5 / GIG-103): detect attached claude session via .cns/.obsidian-bridge.json sentinel and route through unix socket. See architecture §4.2.

/**
 * bridge/claudeCode.ts — async-iterable contract for invoking Claude skills.
 *
 * In Phases 2-4, the only backend is shell-out: spawn `claude code -p /<name>`
 * with the given args, line-buffer stdout/stderr, and yield each line as it
 * arrives. Phase 5 (GIG-103) will layer attached-session detection (sentinel
 * file -> unix socket) on top of this same contract; see architecture §4.1
 * and §4.3. Until then, callers see one consistent shape from this module
 * regardless of how the work eventually executes.
 *
 * The shape is locked by architecture §4.3:
 *
 *   AsyncIterable<
 *     | { stream: 'stdout' | 'stderr', line: string }
 *     | { done: true, exitCode: number }
 *   >
 *
 * Lifecycle / cancellation:
 *   - Closing a consumer (e.g. the modal) does NOT abort the underlying
 *     process. Per architecture §3, long ops keep running because the CLI
 *     is mid-write and aborting is unsafe.
 *   - Explicit cancellation flows through `opts.signal` (AbortSignal). When
 *     fired, we send SIGTERM to the child; the close handler still yields
 *     a final {done: true, exitCode} chunk.
 */

import { spawn } from "child_process";

/** A single chunk yielded by `runSkill`. */
export type BridgeChunk =
  | { stream: "stdout" | "stderr"; line: string }
  | { done: true; exitCode: number };

export interface RunSkillOpts {
  /** Working directory for the spawned process. Should be the vault root. */
  cwd: string;
  /** If aborted, the child process is killed with SIGTERM. */
  signal?: AbortSignal;
}

/**
 * Dependency-injection seam for tests. Production code uses the default
 * `spawn` import; tests override it with a fake child factory.
 */
export interface RunSkillDeps {
  spawn?: typeof spawn;
}

/**
 * Spawn `claude code -p /<name> <...args>` and stream its output line-by-line.
 *
 * Implementation notes:
 *   - We buffer stdout/stderr by newline. Partial trailing buffers are flushed
 *     as their own line on close (the CLI may emit a final line without \n).
 *   - The async generator is driven by an internal queue. Listeners on the
 *     child push into the queue; the generator awaits a resolver when empty.
 *   - We deliberately do not promise any ordering guarantee between stdout
 *     and stderr beyond OS-level interleaving. Both streams flow through the
 *     same queue in arrival order.
 */
export async function* runSkill(
  name: string,
  args: string[],
  opts: RunSkillOpts,
  deps: RunSkillDeps = {},
): AsyncIterable<BridgeChunk> {
  const spawnFn = deps.spawn ?? spawn;
  const child = spawnFn(
    "claude",
    ["code", "-p", `/${name}`, ...args],
    { cwd: opts.cwd, stdio: ["ignore", "pipe", "pipe"] },
  );

  const queue: BridgeChunk[] = [];
  let resolver: (() => void) | null = null;
  let finished = false;
  let pendingError: Error | null = null;

  const wake = (): void => {
    const r = resolver;
    resolver = null;
    if (r) r();
  };

  const push = (chunk: BridgeChunk): void => {
    queue.push(chunk);
    wake();
  };

  // Line buffering per stream. Trailing partial line flushed on close.
  const buffers: Record<"stdout" | "stderr", string> = {
    stdout: "",
    stderr: "",
  };

  const handleData = (stream: "stdout" | "stderr", data: Buffer): void => {
    buffers[stream] += data.toString("utf8");
    let idx: number;
    while ((idx = buffers[stream].indexOf("\n")) !== -1) {
      const line = buffers[stream].slice(0, idx).replace(/\r$/, "");
      buffers[stream] = buffers[stream].slice(idx + 1);
      push({ stream, line });
    }
  };

  const flushTrailing = (stream: "stdout" | "stderr"): void => {
    if (buffers[stream].length > 0) {
      push({ stream, line: buffers[stream] });
      buffers[stream] = "";
    }
  };

  // stdout/stderr are guaranteed non-null because we passed
  // stdio: ["ignore", "pipe", "pipe"] above. The narrower type is enforced
  // here rather than via a cast on the spawn result so we don't leak a
  // non-portable `ChildProcessWithoutNullStreams` cast for tests.
  child.stdout?.on("data", (d: Buffer) => handleData("stdout", d));
  child.stderr?.on("data", (d: Buffer) => handleData("stderr", d));

  child.on("error", (err) => {
    pendingError = err instanceof Error ? err : new Error(String(err));
    finished = true;
    wake();
  });

  child.on("close", (code) => {
    flushTrailing("stdout");
    flushTrailing("stderr");
    push({ done: true, exitCode: code ?? -1 });
    finished = true;
    wake();
  });

  const onAbort = (): void => {
    try {
      child.kill("SIGTERM");
    } catch {
      // Process may already be gone — ignore.
    }
  };
  if (opts.signal) {
    if (opts.signal.aborted) {
      onAbort();
    } else {
      opts.signal.addEventListener("abort", onAbort, { once: true });
    }
  }

  try {
    while (true) {
      if (queue.length > 0) {
        const next = queue.shift()!;
        yield next;
        if ("done" in next && next.done) return;
        continue;
      }
      if (finished) {
        if (pendingError) throw pendingError;
        return;
      }
      await new Promise<void>((resolve) => {
        resolver = resolve;
      });
    }
  } finally {
    if (opts.signal) {
      opts.signal.removeEventListener("abort", onAbort);
    }
  }
}
