/**
 * Pure-logic surface of `conflictsActions.ts` — no Obsidian imports,
 * unit-testable in node. Mirrors the architectural boundary set by
 * `betActions.predicates.ts` (architecture §1.1).
 *
 * Format reference: `cns/conflicts.py:render_conflicts_file`. Each conflict
 * is rendered as
 *
 *   ### C-YYYY-MM-DD-<slug> (N days open)
 *   - **First detected:** <iso>
 *   - **Bet:** [[bet_<file>]]
 *   - **Trigger:** <text>
 *
 * The post-processor needs three predicates:
 *   - extract the conflict id from a heading text node
 *   - extract the bet wikilink target from a bullet block belonging to a
 *     specific conflict heading
 *   - derive a fallback bet target when no `**Bet:**` line is present
 */

/**
 * Conflict id regex, mirrored from `vaultState.ts` (CONFLICT_HEADING_RE).
 *
 * The slug character class is `[a-z0-9_-]+` (hyphen LAST so it isn't read as
 * a range). The detector emits hyphenated suffixes (`-needs-sparring`,
 * `-killed-trigger`, `-vs-...`); regressing this back to underscore-only
 * would lose every conflict carrying those suffixes. The vaultState fix
 * landed already — keep the two regexes in lockstep.
 */
const CONFLICT_ID_RE = /^(C-\d{4}-\d{2}-\d{2}-[a-z0-9_-]+)\b/;

/**
 * Pull the conflict id out of an h3's text content. The heading is rendered
 * by Obsidian as `<h3>C-2026-04-29-foo (3 days open)</h3>` (with a possible
 * trailing parenthetical). We anchor on the prefix; everything after the
 * id is ignored.
 *
 * Returns null when the heading is something else (e.g. a section header).
 */
export function extractConflictId(headingText: string): string | null {
  const trimmed = headingText.trim();
  const m = CONFLICT_ID_RE.exec(trimmed);
  return m ? m[1] : null;
}

/**
 * Derive the bet-file target when the bullet list under the heading lacks a
 * `**Bet:**` entry. The conflict id is `C-YYYY-MM-DD-<slug>`; the slug after
 * the date prefix is the bet stem, so `bet_<slug>` is the canonical fallback.
 *
 * Returns null when the conflict id does not parse — callers should not
 * render an Open-bet button in that case.
 */
export function fallbackBetTarget(conflictId: string): string | null {
  const m = /^C-\d{4}-\d{2}-\d{2}-(.+)$/.exec(conflictId);
  if (!m) return null;
  return `bet_${m[1]}`;
}

/**
 * Scan an array of bullet-list lines (already stripped of HTML, one bullet
 * per entry) for the `**Bet:**` line and pull out the wikilink target.
 *
 * Format from `cns/conflicts.py`: `- **Bet:** [[bet_foo]]`. The target may
 * or may not include `.md`; we strip it to match `openLinkText` semantics
 * (which resolves bare basenames the same as `<basename>.md`).
 *
 * Returns null when no `**Bet:**` line is present or it carries no
 * wikilink — callers should fall back to `fallbackBetTarget`.
 */
export function extractBetWikilink(bulletText: string): string | null {
  // The bullet may arrive with or without the leading "- " marker depending
  // on how the caller extracted it; tolerate both.
  const stripped = bulletText.replace(/^\s*-\s*/, "");
  if (!/^\*\*Bet:\*\*/.test(stripped)) return null;
  const wiki = /\[\[([^\]]+)\]\]/.exec(stripped);
  if (!wiki) return null;
  const inner = wiki[1].trim();
  // openLinkText resolves both `bet_foo` and `bet_foo.md`; normalize to the
  // bare basename for consistency with how vaultState renders bet links.
  return inner.replace(/\.md$/, "");
}

/**
 * Resolve the open-bet target for a conflict heading. Walks the bullet
 * lines (in source order) looking for the `**Bet:**` entry; falls back to
 * `bet_<slug>` derived from the conflict id when no match is found.
 *
 * Pure: takes plain strings, returns a plain string or null.
 */
export function resolveBetTarget(
  conflictId: string,
  bulletLines: string[],
): string | null {
  for (const line of bulletLines) {
    const target = extractBetWikilink(line);
    if (target) return target;
  }
  return fallbackBetTarget(conflictId);
}

/**
 * Derive the slug portion of a conflict id (everything after `C-YYYY-MM-DD-`).
 * Exposed so tests can pin the date-prefix stripping behavior.
 */
export function conflictIdSlug(conflictId: string): string | null {
  const m = /^C-\d{4}-\d{2}-\d{2}-(.+)$/.exec(conflictId);
  return m ? m[1] : null;
}
