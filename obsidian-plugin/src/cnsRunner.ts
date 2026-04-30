/**
 * cnsRunner — discovers the `cns` Python CLI binary and runs it on behalf of
 * the plugin. Lives entirely in the plugin process (Obsidian desktop, Node
 * runtime via Electron). All command output is captured and returned so the
 * plugin can surface results inside the vault — never make the user shell out.
 */

import { spawn } from "child_process";
import { access, constants } from "fs/promises";
import { homedir } from "os";
import { join } from "path";

export interface RunResult {
  stdout: string;
  stderr: string;
  code: number;
}

export interface RunOptions {
  cwd?: string;
  /** Optional timeout in ms. Default: 30s. */
  timeoutMs?: number;
  /**
   * Optional cancellation signal. When the signal aborts (e.g. plugin
   * unload), the spawned child is sent SIGTERM. If the signal is already
   * aborted at call time the child is killed immediately.
   */
  signal?: AbortSignal;
}

/**
 * Thrown when no `cns` binary can be located. The message is surfaced verbatim
 * in the settings panel, so it must be actionable.
 */
export class CnsBinaryNotFoundError extends Error {
  constructor(triedPaths: string[]) {
    const lines = [
      "Could not locate the cns binary.",
      "",
      "Tried:",
      ...triedPaths.map((p) => `  - ${p}`),
      "",
      "Install the CLI with:",
      "  pip install git+https://github.com/kunggaochicken/GigaBrain.git",
      "",
      "Or set an explicit path in GigaBrain CNS settings.",
    ];
    super(lines.join("\n"));
    this.name = "CnsBinaryNotFoundError";
  }
}

/**
 * Probe the filesystem for an executable at `candidate`. Returns the path on
 * success, otherwise null. Exposed for testing.
 */
export async function isExecutable(candidate: string): Promise<boolean> {
  try {
    await access(candidate, constants.X_OK);
    return true;
  } catch {
    return false;
  }
}

/**
 * Run `which <name>` and return the first line of stdout, or null if not on
 * PATH. Exposed for tests via the `runner` injection point in `discoverBinary`.
 */
export async function whichCns(
  name: string,
  runner: typeof run = run,
): Promise<string | null> {
  try {
    const result = await runner("which", [name], { timeoutMs: 5000 });
    if (result.code !== 0) return null;
    const first = result.stdout.split("\n")[0].trim();
    return first.length > 0 ? first : null;
  } catch {
    return null;
  }
}

/**
 * Resolve the cns binary path. Resolution order:
 *   1. Explicit override (from settings)
 *   2. ~/.local/bin/cns (the documented pip --user install location)
 *   3. `which cns` on PATH
 *
 * Throws CnsBinaryNotFoundError if none resolve.
 *
 * The `deps` parameter is dependency injection for tests. Production callers
 * should omit it.
 */
export async function discoverBinary(
  override?: string,
  deps: {
    isExecutable?: (p: string) => Promise<boolean>;
    which?: (name: string) => Promise<string | null>;
    home?: () => string;
  } = {},
): Promise<string> {
  const exists = deps.isExecutable ?? isExecutable;
  const lookup = deps.which ?? ((n: string) => whichCns(n));
  const home = deps.home ?? homedir;

  const tried: string[] = [];

  if (override && override.trim().length > 0) {
    tried.push(`settings override: ${override}`);
    if (await exists(override)) return override;
  }

  const localBin = join(home(), ".local", "bin", "cns");
  tried.push(localBin);
  if (await exists(localBin)) return localBin;

  tried.push("which cns (PATH)");
  const fromPath = await lookup("cns");
  if (fromPath) return fromPath;

  throw new CnsBinaryNotFoundError(tried);
}

/**
 * Probe the cns binary for a version string. The CLI does not currently expose
 * `--version`, so this falls back to parsing `cns --help` and returning the
 * first non-empty line as a presence signal. If even `--help` fails, throws.
 *
 * Returns a short human-readable string suitable for the settings panel.
 */
export async function probeVersion(binPath: string): Promise<string> {
  // Try --version first (in case a future CLI release adds it).
  const versionResult = await run(binPath, ["--version"], { timeoutMs: 5000 });
  if (versionResult.code === 0) {
    const line = versionResult.stdout.split("\n")[0].trim();
    if (line.length > 0) return line;
  }

  // Fallback: --help. The CLI prints "Usage: cns ..." which confirms presence.
  const helpResult = await run(binPath, ["--help"], { timeoutMs: 5000 });
  if (helpResult.code !== 0) {
    throw new Error(
      `cns binary at ${binPath} did not respond to --help (exit ${helpResult.code}): ${helpResult.stderr.trim()}`,
    );
  }
  // Without an explicit version, report "installed" so the panel shows green.
  return "installed (version flag not exposed by CLI)";
}

/**
 * Run an arbitrary cns command and capture its output. Never throws on
 * non-zero exit — callers inspect `code` and decide.
 */
export function run(
  binPath: string,
  args: string[],
  opts: RunOptions = {},
): Promise<RunResult> {
  return new Promise((resolve, reject) => {
    const child = spawn(binPath, args, {
      cwd: opts.cwd,
      stdio: ["ignore", "pipe", "pipe"],
    });

    let stdout = "";
    let stderr = "";
    let timedOut = false;

    const timeoutMs = opts.timeoutMs ?? 30_000;
    const timer = setTimeout(() => {
      timedOut = true;
      child.kill("SIGTERM");
    }, timeoutMs);

    // Wire opts.signal to child.kill so callers can cancel an in-flight run
    // (e.g. the bet watcher's dispose() flow on plugin unload). Both this
    // listener and the timeout above must be torn down on natural exit so
    // neither leaks the other's handler.
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
    const cleanup = (): void => {
      clearTimeout(timer);
      opts.signal?.removeEventListener?.("abort", onAbort);
    };

    child.stdout?.on("data", (chunk) => {
      stdout += chunk.toString();
    });
    child.stderr?.on("data", (chunk) => {
      stderr += chunk.toString();
    });

    child.on("error", (err) => {
      cleanup();
      reject(err);
    });

    child.on("close", (code) => {
      cleanup();
      if (timedOut) {
        reject(new Error(`cns command timed out after ${timeoutMs}ms: ${binPath} ${args.join(" ")}`));
        return;
      }
      resolve({ stdout, stderr, code: code ?? -1 });
    });
  });
}
