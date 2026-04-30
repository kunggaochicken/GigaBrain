/**
 * vaultState — pure reducer that scans a vault on disk and produces the
 * `VaultState` consumed by the sidebar (Phase 1) and status bar (Phase 2).
 *
 * Hard rules per architecture §1.1 / §1.2:
 *   - No Obsidian APIs; this module is unit-testable in node.
 *   - Frontmatter only, never markdown bodies.
 *   - On per-file parse failure: `console.warn` and skip. No badge / sidebar
 *     surface (§7.4).
 *   - The vault is the source of truth. No caching across rebuilds.
 *
 * Detection rules are mirrored from architecture §2.2 — read that section
 * before changing anything here.
 */

import { readdir, readFile } from "fs/promises";
import { join, relative, sep } from "path";

import matter from "gray-matter";

// ---------------------------------------------------------------------------
// Public types
// ---------------------------------------------------------------------------

export type VaultState = {
  pendingBriefs: BriefRef[];
  openConflicts: ConflictRef[];
  staleBets: BetRef[];
  /** Incremented on every successful scan; views diff to skip pointless renders. */
  generation: number;
  /** Epoch ms; surfaced in the sidebar footer. */
  scannedAt: number;
};

export type BriefRef = {
  briefPath: string;
  betSlug: string;
  owner: string;
  agentRunId: string;
  proposedClosure: boolean;
  costUsd?: number;
};

export type ConflictRef = {
  id: string;
  betFile: string;
  owner: string;
  firstDetected: string;
  daysOpen: number;
  trigger: string;
  anchor: string;
};

export type BetRef = {
  betPath: string;
  slug: string;
  owner: string;
  /** ISO date string, or empty when never reviewed. */
  lastReviewed: string;
  daysSinceReview: number;
  killCriteriaUnspecified: boolean;
};

export type ScanOptions = {
  vaultRoot: string;
  reviewsDir: string; // default "Brain/Reviews"
  conflictsFile: string; // default "Brain/CONFLICTS.md"
  betsDir: string; // default "Brain/Bets"
  staleAfterDays: number; // default 30 (per §7.3)
  /** Injected for testability. */
  today: Date;
};

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** The legacy sentinel that flags an active bet as needing sparring. Em-dash matters. */
const KILL_CRITERIA_UNSPECIFIED = "unspecified — needs sparring";

const MS_PER_DAY = 24 * 60 * 60 * 1000;

let GENERATION_COUNTER = 0;

// ---------------------------------------------------------------------------
// Public scan
// ---------------------------------------------------------------------------

/**
 * Scan the vault on disk and produce a fresh VaultState. Pure: no side effects
 * other than per-file `console.warn` on parse failure.
 */
export async function scan(opts: ScanOptions): Promise<VaultState> {
  const [pendingBriefs, openConflicts, staleBets] = await Promise.all([
    scanPendingBriefs(opts),
    scanOpenConflicts(opts),
    scanStaleBets(opts),
  ]);

  GENERATION_COUNTER += 1;
  return {
    pendingBriefs,
    openConflicts,
    staleBets,
    generation: GENERATION_COUNTER,
    scannedAt: Date.now(),
  };
}

// ---------------------------------------------------------------------------
// Pending briefs
// ---------------------------------------------------------------------------

/**
 * Find every `<reviewsDir>/**\/brief.md` (any depth) — accommodates both flat
 * `<reviewsDir>/<slug>/brief.md` and per-leader `<reviewsDir>/<id>/<slug>/brief.md`
 * layouts (§2.2 / §7.6). v1 treats them as siblings.
 */
async function scanPendingBriefs(opts: ScanOptions): Promise<BriefRef[]> {
  const root = join(opts.vaultRoot, opts.reviewsDir);
  const briefPaths = await findFilesByName(root, "brief.md");

  const refs: BriefRef[] = [];
  for (const absPath of briefPaths) {
    const fm = await readFrontmatter(absPath);
    if (!fm) continue;
    if (fm.status !== "pending") continue;

    const betSlug = typeof fm.bet === "string" && fm.bet.length > 0
      ? fm.bet
      : deriveSlugFromBriefPath(absPath, root);
    const owner = typeof fm.owner === "string" ? fm.owner : "";
    const agentRunId = typeof fm.agent_run_id === "string" ? fm.agent_run_id : "";
    const proposedClosure = fm.proposed_closure === true;
    let costUsd: number | undefined;
    if (
      fm.cost &&
      typeof fm.cost === "object" &&
      typeof (fm.cost as { usd?: unknown }).usd === "number"
    ) {
      costUsd = (fm.cost as { usd: number }).usd;
    }

    refs.push({
      briefPath: vaultRelative(opts.vaultRoot, absPath),
      betSlug,
      owner,
      agentRunId,
      proposedClosure,
      ...(costUsd !== undefined ? { costUsd } : {}),
    });
  }

  // Oldest-first by agentRunId — matches `cns reviews list`.
  refs.sort((a, b) => a.agentRunId.localeCompare(b.agentRunId));
  return refs;
}

/**
 * The brief lives at `<reviewsDir>/[<leader>/]<slug>/brief.md`. We use the
 * directory immediately above `brief.md` as the slug fallback when frontmatter
 * is missing the `bet:` field.
 */
function deriveSlugFromBriefPath(absPath: string, reviewsRoot: string): string {
  const rel = relative(reviewsRoot, absPath);
  const parts = rel.split(sep);
  // brief.md sits at parts[parts.length - 1]; its parent dir is parts[len - 2].
  return parts.length >= 2 ? parts[parts.length - 2] : "";
}

// ---------------------------------------------------------------------------
// Open conflicts
// ---------------------------------------------------------------------------

// Slug suffix is `make_conflict_id`-emitted (`cns/conflicts.py`): the slug part
// is built by `cns/detector.py` and routinely contains hyphens (e.g.
// `-needs-sparring`, `-killed-trigger`, `-vs-...`). Hyphen is placed last in the
// character class so it isn't interpreted as a range.
const CONFLICT_HEADING_RE = /^### (C-\d{4}-\d{2}-\d{2}-[a-z0-9_-]+)\b/;
const ROLE_HEADING_RE = /^## .+ \(([a-z0-9_-]+)\)/;

/**
 * Parse `CONFLICTS.md`. Format is locked by `cns/conflicts.py:render_conflicts_file`.
 * We extract owner from the parent `## Role Name (id)` heading and fields from
 * the bullet block beneath each `### C-...` heading.
 */
async function scanOpenConflicts(opts: ScanOptions): Promise<ConflictRef[]> {
  const conflictsAbs = join(opts.vaultRoot, opts.conflictsFile);
  let text: string;
  try {
    text = await readFile(conflictsAbs, "utf8");
  } catch {
    // No CONFLICTS.md is fine — empty queue.
    return [];
  }

  const lines = text.split("\n");
  const refs: ConflictRef[] = [];
  let currentOwner = "";

  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i];
    const roleMatch = line.match(ROLE_HEADING_RE);
    if (roleMatch) {
      currentOwner = roleMatch[1];
      continue;
    }
    const headingMatch = line.match(CONFLICT_HEADING_RE);
    if (!headingMatch) continue;

    const id = headingMatch[1];
    let betFile = "";
    let firstDetected = "";
    let trigger = "";

    // Walk the bullet block until the next heading or blank-then-heading.
    for (let j = i + 1; j < lines.length; j += 1) {
      const inner = lines[j];
      if (inner.startsWith("### ") || inner.startsWith("## ")) break;
      if (inner.startsWith("- **Bet:**")) {
        betFile = extractBetFile(inner);
      } else if (inner.startsWith("- **First detected:**")) {
        firstDetected = stripPrefix(inner, "- **First detected:**").trim();
      } else if (inner.startsWith("- **Trigger:**")) {
        trigger = stripPrefix(inner, "- **Trigger:**").trim().slice(0, 120);
      }
    }

    const daysOpen = computeDaysBetween(firstDetected, opts.today);

    refs.push({
      id,
      betFile,
      owner: currentOwner,
      firstDetected,
      daysOpen,
      trigger,
      anchor: id,
    });
  }

  return refs;
}

function stripPrefix(line: string, prefix: string): string {
  return line.startsWith(prefix) ? line.slice(prefix.length) : line;
}

/**
 * Bet field is rendered as `[[bet_foo]]` or `bet_foo.md`. We surface a stable
 * filename suitable for `openLinkText`.
 */
function extractBetFile(line: string): string {
  const wikilink = line.match(/\[\[([^\]]+)\]\]/);
  if (wikilink) {
    const inner = wikilink[1];
    return inner.endsWith(".md") ? inner : `${inner}.md`;
  }
  const trailing = stripPrefix(line, "- **Bet:**").trim();
  return trailing;
}

// ---------------------------------------------------------------------------
// Stale bets
// ---------------------------------------------------------------------------

/**
 * Glob `<betsDir>/bet_*.md` and apply the staleness rules in §2.2.
 *
 * A bet is stale when it is `status: active` AND any of:
 *   - kill_criteria == "unspecified — needs sparring"
 *   - last_reviewed older than `staleAfterDays`
 *   - deferred_until is set AND `<= today` (deferral expired)
 *
 * Missing `last_reviewed` is treated as "never reviewed" and therefore stale.
 */
async function scanStaleBets(opts: ScanOptions): Promise<BetRef[]> {
  const betsRoot = join(opts.vaultRoot, opts.betsDir);
  let entries: string[];
  try {
    entries = await readdir(betsRoot);
  } catch {
    return [];
  }

  const refs: BetRef[] = [];
  for (const name of entries) {
    if (!name.startsWith("bet_") || !name.endsWith(".md")) continue;
    const absPath = join(betsRoot, name);
    const fm = await readFrontmatter(absPath);
    if (!fm) continue;
    if (fm.status !== "active") continue;

    const slug = name.replace(/^bet_/, "").replace(/\.md$/, "");
    const owner = typeof fm.owner === "string" ? fm.owner : "";
    const lastReviewedRaw = fm.last_reviewed;
    const lastReviewed = isIsoDate(lastReviewedRaw) ? lastReviewedRaw : "";
    const daysSinceReview = lastReviewed
      ? computeDaysBetween(lastReviewed, opts.today)
      : Number.POSITIVE_INFINITY;

    const killCriteria = typeof fm.kill_criteria === "string" ? fm.kill_criteria : "";
    const killCriteriaUnspecified = killCriteria === KILL_CRITERIA_UNSPECIFIED;

    const deferredUntilRaw = fm.deferred_until;
    const deferredUntil = isIsoDate(deferredUntilRaw) ? deferredUntilRaw : "";
    const deferralExpired = deferredUntil
      ? parseIsoDate(deferredUntil).getTime() <= startOfDayUtc(opts.today).getTime()
      : false;

    // If a deferral is still in the future, the bet is explicitly NOT stale,
    // even if last_reviewed is old (per §2.2 / spec test).
    const inActiveDeferral = deferredUntil && !deferralExpired;
    if (inActiveDeferral) continue;

    const isStale =
      killCriteriaUnspecified ||
      daysSinceReview > opts.staleAfterDays ||
      deferralExpired;

    if (!isStale) continue;

    refs.push({
      betPath: vaultRelative(opts.vaultRoot, absPath),
      slug,
      owner,
      lastReviewed,
      daysSinceReview: Number.isFinite(daysSinceReview)
        ? daysSinceReview
        : Number.POSITIVE_INFINITY,
      killCriteriaUnspecified,
    });
  }

  return refs;
}

// ---------------------------------------------------------------------------
// Helpers — frontmatter, paths, dates
// ---------------------------------------------------------------------------

/** Read a markdown file's frontmatter as a plain object, or null on failure. */
async function readFrontmatter(absPath: string): Promise<Record<string, unknown> | null> {
  let text: string;
  try {
    text = await readFile(absPath, "utf8");
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    console.warn(`vaultState: failed to parse ${absPath}: ${msg}`);
    return null;
  }
  try {
    const parsed = matter(text);
    return (parsed.data as Record<string, unknown>) ?? {};
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    console.warn(`vaultState: failed to parse ${absPath}: ${msg}`);
    return null;
  }
}

/**
 * Recursively walk a directory tree and return absolute paths of every file
 * named exactly `targetName`. Silently treats missing directories as empty.
 */
async function findFilesByName(root: string, targetName: string): Promise<string[]> {
  const matches: string[] = [];
  await walk(root, async (entry, abs) => {
    if (entry.isFile() && entry.name === targetName) {
      matches.push(abs);
    }
  });
  return matches;
}

type DirentLike = { name: string; isFile(): boolean; isDirectory(): boolean };

async function walk(
  dir: string,
  visit: (entry: DirentLike, abs: string) => Promise<void>,
): Promise<void> {
  let entries: DirentLike[];
  try {
    entries = (await readdir(dir, { withFileTypes: true })) as unknown as DirentLike[];
  } catch {
    return;
  }
  for (const entry of entries) {
    const abs = join(dir, entry.name);
    await visit(entry, abs);
    if (entry.isDirectory()) {
      await walk(abs, visit);
    }
  }
}

function vaultRelative(vaultRoot: string, absPath: string): string {
  // Use forward slashes — Obsidian's openLinkText expects vault-style paths.
  return relative(vaultRoot, absPath).split(sep).join("/");
}

function isIsoDate(value: unknown): value is string {
  if (typeof value === "string") {
    return /^\d{4}-\d{2}-\d{2}/.test(value);
  }
  if (value instanceof Date) {
    return !Number.isNaN(value.getTime());
  }
  return false;
}

/**
 * gray-matter parses YAML dates as `Date` objects. Normalize to YYYY-MM-DD.
 */
function parseIsoDate(value: string | Date): Date {
  if (value instanceof Date) {
    return startOfDayUtc(value);
  }
  // Anchor to UTC midnight to keep day arithmetic timezone-stable.
  const [y, m, d] = value.slice(0, 10).split("-").map((s) => Number.parseInt(s, 10));
  return new Date(Date.UTC(y, (m ?? 1) - 1, d ?? 1));
}

function startOfDayUtc(date: Date): Date {
  return new Date(
    Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate()),
  );
}

function computeDaysBetween(fromIso: string | Date, today: Date): number {
  if (!fromIso) return Number.POSITIVE_INFINITY;
  const from = parseIsoDate(fromIso);
  const to = startOfDayUtc(today);
  const diff = to.getTime() - from.getTime();
  return Math.max(0, Math.round(diff / MS_PER_DAY));
}

// Exposed for tests that want to assert against the sentinel literal.
export const _internals = {
  KILL_CRITERIA_UNSPECIFIED,
};
