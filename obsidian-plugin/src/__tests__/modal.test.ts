/**
 * Tests for `views/modal.RunSkillModal`.
 *
 * Architecture §5.2 calls modals "hard-to-test"; we cover the load-bearing
 * lifecycle invariant here: closing the modal must NOT leave the consume
 * loop appending output into a detached `logEl` (PR #56 Codex review). Once
 * `onClose()` runs, further chunks fed through the iterable must be dropped
 * silently.
 *
 * The bridge contract (bridge/claudeCode.ts) does not require draining the
 * iterable for the spawned child to exit cleanly — `child.kill` is the only
 * abort path — so the chosen fix is to gate `appendLine`/`markDone` on a
 * `closed` flag and break out of the consume loop on the next tick.
 *
 * The `obsidian` import inside `views/modal.ts` is rewired to a tiny shim
 * via `vitest.config.ts` (`alias: { obsidian: '...stubs/obsidian.ts' }`).
 */

import { describe, expect, it } from "vitest";

import type { BridgeChunk } from "../bridge/claudeCode";
import { RunSkillModal } from "../views/modal";

/**
 * A controllable async iterable: tests push chunks, then resolve the
 * generator's pending await by calling `next()` to feed the modal exactly
 * one chunk at a time. This lets the test interleave `modal.close()` with
 * stream delivery.
 */
function makeControlledStream(): {
  iter: AsyncIterable<BridgeChunk>;
  push: (chunk: BridgeChunk) => Promise<void>;
  end: () => void;
} {
  const queue: BridgeChunk[] = [];
  let resolver: (() => void) | null = null;
  let ended = false;

  const wake = (): void => {
    const r = resolver;
    resolver = null;
    if (r) r();
  };

  const iter: AsyncIterable<BridgeChunk> = {
    async *[Symbol.asyncIterator]() {
      while (true) {
        while (queue.length > 0) {
          yield queue.shift()!;
        }
        if (ended) return;
        await new Promise<void>((resolve) => {
          resolver = resolve;
        });
      }
    },
  };

  return {
    iter,
    push: async (chunk: BridgeChunk): Promise<void> => {
      queue.push(chunk);
      wake();
      // Yield to the event loop so the modal's consume loop runs.
      await new Promise((r) => setTimeout(r, 0));
    },
    end: () => {
      ended = true;
      wake();
    },
  };
}

describe("RunSkillModal close-flag gate", () => {
  it("does not append further log output after onClose", async () => {
    const stream = makeControlledStream();
    const factory = () => stream.iter;

    // Cast to `any` for the App arg — the stub's App is structural, and
    // this test only cares about lifecycle, not Obsidian wiring.
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const modal = new RunSkillModal({} as any, "Dispatch foo", factory);
    modal.open();

    // Push one chunk pre-close: this should make it into logEl.
    await stream.push({ stream: "stdout", line: "line-1" });

    const logEl = (modal as unknown as { logEl: { children: unknown[] } })
      .logEl;
    expect(logEl).not.toBeNull();
    const beforeCloseChildCount = logEl.children.length;
    expect(beforeCloseChildCount).toBeGreaterThan(0);

    // Close the modal (intentionally non-aborting, per arch §3).
    modal.close();

    expect((modal as unknown as { closed: boolean }).closed).toBe(true);
    // logEl is dereferenced; the previously-rendered children are no longer
    // reachable through the modal — the post-close invariant we care about.
    expect((modal as unknown as { logEl: unknown }).logEl).toBeNull();

    // Push more chunks AFTER close. Pre-fix these would silently accumulate
    // spans into the detached logEl forever.
    await stream.push({ stream: "stdout", line: "line-after-close-1" });
    await stream.push({ stream: "stderr", line: "line-after-close-2" });
    await stream.push({ done: true, exitCode: 0 });
    stream.end();

    // The captured logEl (held in the test scope) saw only the pre-close
    // append; nothing was added after close.
    expect(logEl.children.length).toBe(beforeCloseChildCount);
  });

  it("ignores the terminating done chunk if it arrives after close", async () => {
    const stream = makeControlledStream();
    const factory = () => stream.iter;

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const modal = new RunSkillModal({} as any, "Spar foo", factory);
    modal.open();

    const footerEl = (modal as unknown as {
      footerEl: { children: unknown[] };
    }).footerEl;
    expect(footerEl).not.toBeNull();

    modal.close();

    // markDone should be a no-op when closed: no exception, no mutation of
    // a now-null footerEl, and the consume loop should terminate.
    await stream.push({ done: true, exitCode: 0 });
    stream.end();

    expect((modal as unknown as { footerEl: unknown }).footerEl).toBeNull();
  });
});
