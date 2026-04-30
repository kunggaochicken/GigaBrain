/**
 * processors/betActions.ts — markdown post-processor that injects the bet
 * file action bar.
 *
 * Trigger condition (architecture §3.1):
 *   - Source path matches `<betsDir>/bet_*.md`
 *   - Frontmatter parses successfully and has a `status:` field
 *
 * Buttons (locked v1 set per §7.1):
 *   - [Dispatch] -> /execute --bet <slug>   (long op, modal log)
 *   - [Spar]     -> /spar    --bet <slug>   (long op, modal log)
 *   - [Open bet] -> focus frontmatter line  (instant, no CLI)
 *
 * Explicitly NOT in v1: [Mark reviewed], [Defer 7d] (filed as GIG-108).
 *
 * Per §7.2, the plugin does not pre-narrate "scoped sparring not supported"
 * — the /spar skill emits that itself as its first stdout line. We just
 * stream whatever it prints.
 *
 * Pure logic lives in `./betActions.predicates.ts` so unit tests can import
 * it without resolving the `obsidian` package (architecture §1.1).
 */

import { MarkdownPostProcessorContext, Notice, setIcon, TFile } from "obsidian";

import type GigaBrainPlugin from "../main";
import { getVaultBasePath } from "../settings";
import { runSkill } from "../bridge/claudeCode";
import { RunSkillModal } from "../views/modal";
import {
  deriveSlug,
  isUnderBetsDir,
  shouldInjectBar,
} from "./betActions.predicates";

/**
 * Resolve the bets directory from settings with a defensive fallback. The
 * sibling GIG-97 agent owns the settings field (`betsDir`); until that
 * lands, we default to the architectural baseline `Brain/Bets`.
 */
function resolveBetsDir(plugin: GigaBrainPlugin): string {
  const fromSettings = (plugin.settings as unknown as { betsDir?: string })
    .betsDir;
  return fromSettings && fromSettings.length > 0 ? fromSettings : "Brain/Bets";
}

/**
 * Entry point registered in `main.ts` via `registerMarkdownPostProcessor`.
 *
 * The post-processor receives the rendered HTML root (`el`) and a context
 * (`ctx`) carrying the source file path. We:
 *   1. Look up the file by `ctx.sourcePath`.
 *   2. Read its raw content via `app.vault.read()` to get frontmatter.
 *   3. Validate the trigger condition.
 *   4. Inject the action bar as the first child of `el`.
 *
 * This is `async` because reading file content is async; Obsidian tolerates
 * async post-processors as long as DOM mutations happen synchronously after
 * the await.
 */
export async function betActionBar(
  el: HTMLElement,
  ctx: MarkdownPostProcessorContext,
  plugin: GigaBrainPlugin,
): Promise<void> {
  const sourcePath = ctx.sourcePath;
  if (!sourcePath) return;

  const filename = sourcePath.split("/").pop() ?? sourcePath;
  const slug = deriveSlug(filename);
  if (!slug) return;

  const betsDir = resolveBetsDir(plugin);
  if (!isUnderBetsDir(sourcePath, betsDir)) return;

  const file = plugin.app.vault.getAbstractFileByPath(sourcePath);
  if (!(file instanceof TFile)) return;

  let content: string;
  try {
    content = await plugin.app.vault.read(file);
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    console.warn(`[GigaBrain CNS] could not read ${sourcePath}: ${msg}`);
    return;
  }

  if (!shouldInjectBar(sourcePath, content, betsDir)) return;

  // Avoid duplicate bars if the post-processor runs twice on the same root
  // (Obsidian re-renders on edit). We tag the element and bail on retry.
  if (el.querySelector(":scope > .gigabrain-action-bar")) return;

  const bar = el.createDiv({ cls: "gigabrain-action-bar" });
  // Move bar to the top of the root.
  el.insertBefore(bar, el.firstChild);

  buildButton(bar, "Dispatch", "play-circle", () => {
    openRunModal(plugin, `Dispatch ${slug}`, "execute", ["--bet", slug]);
  });

  buildButton(bar, "Spar", "swords", () => {
    openRunModal(plugin, `Spar ${slug}`, "spar", ["--bet", slug]);
  });

  buildButton(bar, "Open bet", "file-text", () => {
    openBetFile(plugin, sourcePath);
  });
}

function buildButton(
  parent: HTMLElement,
  label: string,
  icon: string,
  onClick: () => void,
): HTMLButtonElement {
  const btn = parent.createEl("button");
  const iconSpan = btn.createSpan({ cls: "gigabrain-icon" });
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

function openBetFile(plugin: GigaBrainPlugin, sourcePath: string): void {
  const active = plugin.app.workspace.getActiveFile();
  if (active && active.path === sourcePath) {
    // Already open: focus the editor on the frontmatter line. We use
    // workspace.activeEditor where available; fallback to no-op if not in a
    // markdown view.
    const editor = plugin.app.workspace.activeEditor?.editor;
    if (editor) {
      editor.setCursor({ line: 0, ch: 0 });
      editor.focus();
      return;
    }
  }
  // Otherwise, open the file in the workspace.
  void plugin.app.workspace.openLinkText(sourcePath, sourcePath, false);
}
