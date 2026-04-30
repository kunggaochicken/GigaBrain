/**
 * RunSkillModal — streaming log modal for long-running skill invocations.
 *
 * Per architecture §3 (async UX rule), long ops (≥ 2s expected) open a modal
 * with a live log view that pipes the bridge's stdout/stderr line-by-line.
 *
 * Closing the modal does NOT abort the underlying process (the CLI is mid-
 * write and aborting is unsafe). A separate "Stop" button explicitly aborts
 * via the `AbortController` we own for this run.
 *
 * Footer shows "running…" while open and is replaced with `Exit code: N`
 * when the bridge yields its terminating `{done: true}` chunk.
 */

import { App, Modal, setIcon } from "obsidian";

import type { BridgeChunk } from "../bridge/claudeCode";

/**
 * Factory the modal calls to build its iterable. Receiving an `AbortSignal`
 * lets the modal's "Stop" button cancel the underlying spawn. We avoid
 * passing in a pre-built iterable so the caller's `runSkill(...)` can wire
 * the signal that the modal owns.
 */
export type StreamFactory = (signal: AbortSignal) => AsyncIterable<BridgeChunk>;

export class RunSkillModal extends Modal {
  private title: string;
  private factory: StreamFactory;
  private controller = new AbortController();
  private logEl: HTMLElement | null = null;
  private footerEl: HTMLElement | null = null;
  private stopBtn: HTMLButtonElement | null = null;
  // Flipped true in `onClose()`. Gates `appendLine`/`markDone` and breaks the
  // `consume()` loop so a closed modal does not keep buffering output into a
  // detached `logEl` for the lifetime of the (still-running) child process.
  // Per the bridge contract (bridge/claudeCode.ts), draining the iterable is
  // not required for clean child exit — `child.kill` is the only abort path.
  private closed = false;

  constructor(app: App, title: string, factory: StreamFactory) {
    super(app);
    this.title = title;
    this.factory = factory;
  }

  onOpen(): void {
    const { contentEl } = this;
    contentEl.empty();

    // Header: title + Stop + Close.
    const header = contentEl.createDiv({ cls: "gigabrain-modal-header" });
    header.createEl("h3", { text: this.title });

    const buttons = header.createDiv({ cls: "gigabrain-modal-buttons" });

    this.stopBtn = buttons.createEl("button", {
      text: "Stop",
      cls: "mod-warning",
    });
    this.stopBtn.addEventListener("click", () => {
      this.controller.abort();
      if (this.stopBtn) this.stopBtn.disabled = true;
    });

    const closeBtn = buttons.createEl("button", { text: "Close" });
    closeBtn.addEventListener("click", () => {
      // Closing does NOT abort. Process keeps running per architecture §3.
      this.close();
    });

    // Log body.
    this.logEl = contentEl.createEl("pre", { cls: "gigabrain-modal-log" });

    // Footer: running indicator, replaced with exit code on done.
    this.footerEl = contentEl.createDiv({ cls: "gigabrain-modal-footer" });
    this.footerEl.setText("running…");

    // Kick off the stream consumer. We do not await — onOpen must return.
    void this.consume();
  }

  onClose(): void {
    // Note: we deliberately do not abort here. Long ops keep running.
    // Flag the modal as closed so the in-flight `consume()` loop stops
    // writing into the now-detached log element.
    this.closed = true;
    this.logEl = null;
    this.footerEl = null;
    this.stopBtn = null;
    this.contentEl.empty();
  }

  private async consume(): Promise<void> {
    const iter = this.factory(this.controller.signal);
    try {
      for await (const chunk of iter) {
        // The modal was closed mid-stream. Stop pulling from the iterator;
        // the underlying spawn keeps running (closing is non-aborting), but
        // we no longer accumulate its output in memory.
        if (this.closed) return;
        if ("done" in chunk && chunk.done) {
          this.markDone(chunk.exitCode);
          return;
        }
        if ("stream" in chunk) {
          this.appendLine(chunk.stream, chunk.line);
        }
      }
      // Stream ended without an explicit done chunk; surface as unknown exit.
      this.markDone(-1);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      this.appendLine("stderr", `bridge error: ${msg}`);
      this.markDone(-1);
    }
  }

  private appendLine(stream: "stdout" | "stderr", line: string): void {
    if (this.closed || !this.logEl) return;
    const span = this.logEl.createSpan({
      cls: stream === "stderr" ? "stderr" : "stdout",
    });
    span.setText(line + "\n");
    this.logEl.scrollTop = this.logEl.scrollHeight;
  }

  private markDone(exitCode: number): void {
    if (this.closed) return;
    if (this.footerEl) {
      this.footerEl.setText(`Exit code: ${exitCode}`);
    }
    if (this.stopBtn) {
      this.stopBtn.disabled = true;
    }
  }
}

/**
 * Helper used by post-processors: open a `RunSkillModal` titled with a verb
 * + slug, wired to a `runSkill(...)` call. Centralized so callers pass only
 * the bits they own (skill name, args, cwd).
 *
 * `setIcon` is imported here so callers can pre-assemble button visuals
 * without a separate import dance.
 */
export { setIcon };
