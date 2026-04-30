/**
 * Pure-logic surface of `briefActions.ts` — no Obsidian imports, unit-testable
 * in node. Mirrors the split in `betActions.predicates.ts` and keeps the
 * architectural boundary from §1.1 ("pure modules unit-testable in node
 * without Obsidian stubs") clean.
 *
 * The post-processor itself (in `briefActions.ts`) wraps these with
 * Obsidian-side concerns: file IO, DOM injection, modal launch.
 */

import matter from "gray-matter";

/**
 * Decide whether a given source path is inside the configured reviews
 * directory. Trailing slashes on `reviewsDir` are tolerated.
 */
export function isUnderReviewsDir(
  sourcePath: string,
  reviewsDir: string,
): boolean {
  const normalized = reviewsDir.replace(/\/+$/, "");
  return (
    sourcePath === normalized ||
    sourcePath.startsWith(normalized + "/")
  );
}

/**
 * Derive the bet slug from a brief.md path. The brief lives at one of:
 *   - `<reviewsDir>/<slug>/brief.md`                    (flat)
 *   - `<reviewsDir>/<leader>/<slug>/brief.md`           (per-leader)
 *
 * In both cases the slug is the directory immediately above `brief.md`.
 *
 * Returns null when the path does not end in `.../brief.md` under the
 * reviews dir — callers treat null as "do not inject".
 */
export function deriveBriefSlug(
  sourcePath: string,
  reviewsDir: string,
): string | null {
  if (!isUnderReviewsDir(sourcePath, reviewsDir)) return null;
  const parts = sourcePath.split("/");
  if (parts.length < 2) return null;
  if (parts[parts.length - 1] !== "brief.md") return null;
  const parent = parts[parts.length - 2];
  if (!parent || parent.length === 0) return null;
  return parent;
}

/**
 * Predicate the post-processor uses to decide whether to inject the action
 * bar. Returns true only when:
 *   - sourcePath ends in `<reviewsDir>/.../brief.md`
 *   - frontmatter parses
 *   - frontmatter has both `status:` and `bet:` fields
 *
 * On YAML parse failure we console.warn (per architecture §7.4) and return
 * false — never crash.
 */
export function shouldInjectBriefBar(
  sourcePath: string,
  fileContent: string,
  reviewsDir: string,
): boolean {
  if (!isUnderReviewsDir(sourcePath, reviewsDir)) return false;
  const parts = sourcePath.split("/");
  if (parts[parts.length - 1] !== "brief.md") return false;

  const parsed = safeParseFrontmatter(fileContent);
  if (!parsed) return false;
  if (typeof parsed.data?.status === "undefined") return false;
  if (typeof parsed.data?.bet === "undefined") return false;
  return true;
}

/**
 * Decide whether *this* rendered section is the one that should host the
 * action bar. Same pattern as betActions: only the section anchored at line 0
 * gets the bar, every other section short-circuits. Mirrors
 * `betActions.predicates.isFirstSection` so callers are symmetrical.
 */
export function isFirstSection(
  info: { lineStart: number } | null | undefined,
): boolean {
  if (!info) return false;
  return info.lineStart === 0;
}

/**
 * CLI argv for `[Accept]` — passed to `cnsRunner.run`. Locked here so the
 * test pins it independently of the DOM module.
 */
export function acceptArgs(slug: string): string[] {
  return ["reviews", "accept", slug];
}

/**
 * CLI argv for `[Reject]` — passed to `cnsRunner.run`.
 */
export function rejectArgs(slug: string): string[] {
  return ["reviews", "reject", slug];
}

/**
 * Argv for `[Edit-and-rerun]` — passed to the bridge as
 * `runSkill('execute', editAndRerunArgs(slug, notes))`.
 *
 * Notes flow through argv (not stdin, not a vault file) so the plugin never
 * becomes a second write path for review artifacts. See architecture §3.2
 * invariant note.
 */
export function editAndRerunArgs(slug: string, notes: string): string[] {
  return ["--bet", slug, "--all", "--reviewer-notes", notes];
}

/**
 * Wrap `gray-matter` with a try/catch that returns null on parse failure
 * and emits a console.warn. Per architecture §7.4, parse errors are
 * console-only — no user-facing chrome.
 */
export function safeParseFrontmatter(
  content: string,
): { data: Record<string, unknown> } | null {
  try {
    const parsed = matter(content);
    return { data: parsed.data as Record<string, unknown> };
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    console.warn(`[GigaBrain CNS] frontmatter parse failed: ${msg}`);
    return null;
  }
}
