/**
 * processors/conflictsActions.ts — markdown post-processor that injects an
 * action bar next to each `### C-...` heading in `CONFLICTS.md`.
 *
 * Trigger condition (architecture §3.3):
 *   - Source path equals `plugin.settings.conflictsFile`
 *     (default `Brain/CONFLICTS.md`).
 *
 * Buttons (locked v1 set per §3.3 / §7.1):
 *   - [Spar this] -> /spar --conflict <id>   (long op, modal log)
 *   - [Open bet]  -> openLinkText(target, sourcePath, /*newLeaf*\/ true)
 *
 * Explicitly NOT in v1: [Defer 7d] (filed as GIG-108).
 *
 * Per §7.2, the plugin does not pre-narrate "scoped sparring not supported"
 * — the /spar skill emits that itself as its first stdout line. We just
 * stream whatever it prints.
 *
 * Per §1.2 invariant 2, the plugin never edits CONFLICTS.md. The Spar this
 * button fires the skill; the skill writes any resolution.
 *
 * Pure logic lives in `./conflictsActions.predicates.ts` so unit tests can
 * import it without resolving the `obsidian` package (architecture §1.1).
 */

import { MarkdownPostProcessorContext, Notice, setIcon } from "obsidian";

import type GigaBrainPlugin from "../main";
import { getVaultBasePath } from "../settings";
import { runSkill } from "../bridge/claudeCode";
import { RunSkillModal } from "../views/modal";
import {
  extractConflictId,
  resolveBetTarget,
} from "./conflictsActions.predicates";

/**
 * Resolve the conflicts file path from settings with a defensive fallback.
 * Defaults to the architectural baseline `Brain/CONFLICTS.md`.
 */
function resolveConflictsFile(plugin: GigaBrainPlugin): string {
  const fromSettings = plugin.settings.conflictsFile;
  return fromSettings && fromSettings.length > 0
    ? fromSettings
    : "Brain/CONFLICTS.md";
}

/**
 * Entry point registered in `main.ts` via `registerMarkdownPostProcessor`.
 *
 * Unlike `betActions`, the bar is injected **per `### C-...` heading**, not
 * once per file. Each rendered section may carry one or more conflict
 * headings; we walk every `h3` whose text matches the conflict-id regex,
 * harvest the bullet text up to the next heading, resolve the bet target,
 * and inject a `.gigabrain-action-bar` immediately after the heading.
 *
 * Synchronous: the post-processor only reads from the rendered DOM and the
 * sourcePath. No file IO required (the trigger does not need frontmatter).
 */
export function conflictsActionBar(
  el: HTMLElement,
  ctx: MarkdownPostProcessorContext,
  plugin: GigaBrainPlugin,
): void {
  const sourcePath = ctx.sourcePath;
  if (!sourcePath) return;

  const conflictsFile = resolveConflictsFile(plugin);
  if (sourcePath !== conflictsFile) return;

  const headings = el.querySelectorAll("h3");
  for (const heading of Array.from(headings)) {
    const id = extractConflictId(heading.textContent ?? "");
    if (!id) continue;

    // Avoid duplicate bars when Obsidian re-runs the post-processor on edit.
    const next = heading.nextElementSibling;
    if (next && next.classList.contains("gigabrain-action-bar")) continue;

    const bulletLines = harvestBulletLines(heading);
    const betTarget = resolveBetTarget(id, bulletLines);

    const bar = document.createElement("div");
    bar.classList.add("gigabrain-action-bar");

    buildButton(bar, "Spar this", "swords", () => {
      openRunModal(plugin, `Spar ${id}`, "spar", ["--conflict", id]);
    });

    if (betTarget) {
      buildButton(bar, "Open bet", "file-text", () => {
        void plugin.app.workspace.openLinkText(
          betTarget,
          sourcePath,
          true /* newLeaf */,
        );
      });
    }

    heading.insertAdjacentElement("afterend", bar);
  }
}

/**
 * Walk the heading's following siblings (in DOM order) and pull every
 * bullet line we encounter, stopping at the next `h2`/`h3` (the boundary
 * between conflicts, mirrored from `vaultState.scanOpenConflicts`).
 *
 * Obsidian renders `- **Bet:** [[bet_foo]]` as a `<ul><li>...</li></ul>`
 * sibling of the heading. There may also be intervening paragraphs we want
 * to skip without crashing. We harvest the textContent of every `<li>` and
 * also include paragraph text (some renders flatten short bullet blocks);
 * the predicate layer filters non-`**Bet:**` lines.
 */
function harvestBulletLines(heading: Element): string[] {
  const lines: string[] = [];
  let cursor: Element | null = heading.nextElementSibling;
  while (cursor) {
    const tag = cursor.tagName.toLowerCase();
    if (tag === "h3" || tag === "h2" || tag === "h1") break;
    if (tag === "ul" || tag === "ol") {
      for (const li of Array.from(cursor.querySelectorAll(":scope > li"))) {
        lines.push(li.textContent ?? "");
      }
    } else if (tag === "p") {
      // Paragraph fallback for unusual renders; predicate filters non-bet.
      lines.push(cursor.textContent ?? "");
    }
    cursor = cursor.nextElementSibling;
  }
  return lines;
}

function buildButton(
  parent: HTMLElement,
  label: string,
  icon: string,
  onClick: () => void,
): HTMLButtonElement {
  const btn = document.createElement("button");
  parent.appendChild(btn);
  const iconSpan = document.createElement("span");
  iconSpan.classList.add("gigabrain-icon");
  btn.appendChild(iconSpan);
  setIcon(iconSpan, icon);
  btn.appendChild(document.createTextNode(label));
  btn.addEventListener("click", (ev) => {
    ev.preventDefault();
    onClick();
  });
  return btn;
}

function openRunModal(
  plugin: GigaBrainPlugin,
  title: string,
  skill: string,
  args: string[],
): void {
  const cwd = getVaultBasePath(plugin.app);
  if (!cwd) {
    new Notice(
      "GigaBrain CNS: cannot resolve vault path (desktop only).",
      6000,
    );
    return;
  }
  const modal = new RunSkillModal(plugin.app, title, (signal) =>
    runSkill(skill, args, { cwd, signal }),
  );
  modal.open();
}
