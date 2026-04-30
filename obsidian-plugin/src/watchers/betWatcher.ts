/**
 * watchers/betWatcher.ts — debounced auto-reindex on bet file saves
 * (Phase 4 / GIG-102).
 *
 * Architecture §2.3: a separate 1500ms debounce specifically for auto-reindex,
 * scoped narrowly to `<betsDir>/bet_*.md` modify events. After the debouncer
 * settles, we run `cns reindex --check`. Exit-zero short-circuits (nothing
 * changed). Non-zero triggers `cns reindex` and surfaces the result as a
 * Notice. The existing 500ms sidebar debouncer in `main.ts` is independent
 * and untouched: `BETS.md`/`CONFLICTS.md` writes from `cns reindex` flow
 * through the modify watcher there and refresh the sidebar/status bar.
 *
 * Design intent (CLAUDE.md "single console" rule): the leader edits a bet in
 * Obsidian and the index, conflicts, and stale-list converge automatically —
 * no terminal, no `cd`. Failures surface verbatim via a Notice; the leader
 * can drill in if they want, but the default state is "you didn't have to
 * think about it."
 *
 * Cancellation / lifecycle:
 *   - Each modify event cancels-and-resets the timer.
 *   - On plugin unload, `dispose()` clears the timer and aborts any in-flight
 *     reindex via AbortSignal so child processes don't outlive the plugin.
 *   - A separate `reindexInFlight` flag coalesces overlapping triggers — we
 *     never run two reindexes concurrently for the same vault.
 */
import { Notice } from "obsidian";

import { run as runCns, RunResult } from "../cnsRunner";

/**
 * Default debounce window for auto-reindex (milliseconds). Architecture §2.3
 * ratified 1500ms for v1; if it proves too eager during typing, the user can
 * raise it via the `reindexDebounceMs` setting without a code change.
 */
export const DEFAULT_REINDEX_DEBOUNCE_MS = 1500;

/** Truncation length for stderr surfaced in error notices (architecture §3). */
const STDERR_NOTICE_MAX = 2000;

/** Predicate: does `path` look like `<betsDir>/bet_*.md`? */
export function isBetFilePath(path: string, betsDir: string): boolean {
  if (!path || !betsDir) return false;
  // Normalize trailing slash; betsDir is settings-driven.
  const dir = betsDir.endsWith("/") ? betsDir.slice(0, -1) : betsDir;
  if (!path.startsWith(`${dir}/`)) return false;
  const filename = path.slice(dir.length + 1);
  // Reject nested directories: only direct children of <betsDir>. Architecture
  // §2.3 scopes this to `<betsDir>/bet_*.md` specifically.
  if (filename.includes("/")) return false;
  // bet_X.md where X is non-empty.
  return /^bet_.+\.md$/.test(filename);
}

/** Minimal plugin surface the watcher needs — keeps tests free of main.ts. */
export interface BetWatcherHost {
  cnsBinaryPath: string | null;
  vaultRoot: string | null;
  /** Settings access — pulled lazily so the latest value is read at fire-time. */
  getBetsDir: () => string;
  getDebounceMs: () => number;
  /** Optional debug logger; main.ts wires this to the gated console.log. */
  log?: (msg: string) => void;
  /** Optional Notice constructor injection for tests. */
  noticeFn?: (message: string, timeout?: number) => void;
  /** Optional runner injection for tests. */
  runner?: (
    bin: string,
    args: string[],
    opts: { cwd?: string; signal?: AbortSignal; timeoutMs?: number },
  ) => Promise<RunResult>;
}

/**
 * BetWatcher owns the debounce timer + reindex-in-flight lock for one plugin.
 * `handleModify` is the only event entry point; `dispose` is the unload hook.
 */
export class BetWatcher {
  private timer: ReturnType<typeof setTimeout> | null = null;
  private reindexInFlight = false;
  private aborter: AbortController | null = null;
  private disposed = false;

  constructor(private readonly host: BetWatcherHost) {}

  /**
   * Vault `modify` event handler. Filters to `<betsDir>/bet_*.md` and
   * debounces. Adds, deletes, and renames are intentionally ignored
   * (architecture §2.3).
   */
  handleModify(path: string): void {
    if (this.disposed) return;
    const betsDir = this.host.getBetsDir();
    if (!isBetFilePath(path, betsDir)) return;
    this.scheduleReindex();
  }

  /** Public for tests: trigger the debounce timer directly. */
  scheduleReindex(): void {
    if (this.disposed) return;
    if (this.timer !== null) clearTimeout(this.timer);
    const delay = this.host.getDebounceMs();
    this.timer = setTimeout(() => {
      this.timer = null;
      void this.runReindex();
    }, delay);
  }

  /**
   * Run `cns reindex --check`; if non-zero, run `cns reindex`. Surfaces
   * success/failure via Notice. Skips entirely if a reindex is already
   * in flight (the in-flight one will pick up any new changes that landed
   * after it started — and a fresh modify event will retrigger us anyway).
   */
  private async runReindex(): Promise<void> {
    if (this.disposed) return;
    if (this.reindexInFlight) {
      this.host.log?.("reindex skipped: already in flight");
      return;
    }
    const bin = this.host.cnsBinaryPath;
    const cwd = this.host.vaultRoot;
    if (!bin || !cwd) {
      this.host.log?.("reindex skipped: cns binary or vault root unresolved");
      return;
    }

    const notice = this.host.noticeFn ?? defaultNotice;
    const runner = this.host.runner ?? runCns;
    this.reindexInFlight = true;
    this.aborter = new AbortController();
    const signal = this.aborter.signal;

    try {
      const check = await runner(bin, ["reindex", "--check"], {
        cwd,
        signal,
        timeoutMs: 60_000,
      });
      if (this.disposed) return;
      if (check.code === 0) {
        this.host.log?.("reindex --check exit 0; nothing to do");
        return;
      }

      const result = await runner(bin, ["reindex"], {
        cwd,
        signal,
        timeoutMs: 120_000,
      });
      if (this.disposed) return;
      if (result.code === 0) {
        notice("GigaBrain: reindex done", 4000);
        this.host.log?.("reindex completed");
      } else {
        const firstLine = (result.stderr || "")
          .split("\n")
          .map((s) => s.trim())
          .find((s) => s.length > 0) ?? `exit ${result.code}`;
        notice(
          `GigaBrain: reindex failed: ${truncate(firstLine, STDERR_NOTICE_MAX)}`,
          8000,
        );
        this.host.log?.(`reindex failed (exit ${result.code}): ${firstLine}`);
      }
    } catch (err) {
      if (this.disposed) return;
      const msg = err instanceof Error ? err.message : String(err);
      // AbortError on dispose is expected; don't yell at the user.
      if (signal.aborted) {
        this.host.log?.(`reindex aborted: ${msg}`);
        return;
      }
      notice(`GigaBrain: reindex error: ${truncate(msg, STDERR_NOTICE_MAX)}`, 8000);
      this.host.log?.(`reindex threw: ${msg}`);
    } finally {
      this.reindexInFlight = false;
      this.aborter = null;
    }
  }

  /** Plugin unload hook: cancel pending timer + abort in-flight reindex. */
  dispose(): void {
    this.disposed = true;
    if (this.timer !== null) {
      clearTimeout(this.timer);
      this.timer = null;
    }
    if (this.aborter) {
      try {
        this.aborter.abort();
      } catch {
        // Abort may throw on some platforms if the controller is already
        // closed — ignore, the in-flight task will clean itself up.
      }
      this.aborter = null;
    }
  }
}

function defaultNotice(message: string, timeout?: number): void {
  // Wrap in try/catch: in test environments without a DOM, `new Notice` would
  // throw. The watcher tests inject `noticeFn`; production gets the real one.
  try {
    new Notice(message, timeout);
  } catch {
    // No-op: production never trips this.
  }
}

function truncate(s: string, max: number): string {
  if (s.length <= max) return s;
  return `${s.slice(0, max)}…`;
}
