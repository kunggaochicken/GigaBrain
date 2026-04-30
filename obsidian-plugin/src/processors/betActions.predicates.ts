/**
 * Pure-logic surface of `betActions.ts` — no Obsidian imports, unit-testable
 * in node. Keeps the architectural boundary from §1.1 ("pure modules
 * unit-testable in node without Obsidian stubs") clean.
 *
 * The post-processor itself (in `betActions.ts`) wraps these with
 * Obsidian-side concerns: file IO, DOM injection, modal launch.
 */

import matter from "gray-matter";

/**
 * Strip `bet_` prefix and `.md` suffix from a filename to derive the slug
 * we pass to skills. `bet_ship_v1.md` -> `ship_v1`; `bet_open-source.md`
 * -> `open-source`. Returns null if the filename does not match the
 * `bet_*.md` shape.
 */
export function deriveSlug(filename: string): string | null {
  const m = /^bet_(.+)\.md$/.exec(filename);
  return m ? m[1] : null;
}

/**
 * Predicate the post-processor uses to decide whether to inject the action
 * bar. Returns true only when:
 *   - sourcePath is under `<betsDir>/`
 *   - filename matches `bet_*.md`
 *   - frontmatter parses and has a `status:` field
 *
 * On YAML parse failure we console.warn (per architecture §7.4) and return
 * false — never crash.
 */
export function shouldInjectBar(
  sourcePath: string,
  fileContent: string,
  betsDir: string,
): boolean {
  if (!isUnderBetsDir(sourcePath, betsDir)) return false;
  const filename = sourcePath.split("/").pop() ?? sourcePath;
  if (!/^bet_.+\.md$/.test(filename)) return false;

  const parsed = safeParseFrontmatter(fileContent);
  if (!parsed) return false;
  if (typeof parsed.data?.status === "undefined") return false;
  return true;
}

export function isUnderBetsDir(sourcePath: string, betsDir: string): boolean {
  const normalized = betsDir.replace(/\/+$/, "");
  return (
    sourcePath === normalized ||
    sourcePath.startsWith(normalized + "/")
  );
}

/**
 * Decide whether *this* rendered section is the one that should host the
 * action bar. `registerMarkdownPostProcessor` runs once per rendered preview
 * section; without a guard, notes that render into multiple sections get a
 * duplicate bar in each section.
 *
 * Strategy: only the section anchored at the file's first line
 * (`lineStart === 0`) gets the bar. Subsequent sections short-circuit. If
 * `getSectionInfo` returns null (transient render state, embeds, etc.), we
 * also skip — better to miss one render than to duplicate the bar.
 */
export function isFirstSection(
  info: { lineStart: number } | null | undefined,
): boolean {
  if (!info) return false;
  return info.lineStart === 0;
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
