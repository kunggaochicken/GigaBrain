/**
 * processors/briefActions.ts — markdown post-processor that injects the brief
 * file action bar (architecture §3.2, mirrors `/spar` Phase 2 menu).
 *
 * Trigger condition (locked spec):
 *   - Source path matches `<reviewsDir>/**\/brief.md`
 *   - Frontmatter parses successfully and has BOTH `status:` and `bet:` fields
 *
 * Buttons (locked v1 set — do not add or remove):
 *   - [Accept]          -> `cns reviews accept <slug>`         (short op, Notice)
 *   - [Reject]          -> `cns reviews reject <slug>`         (short op, Notice)
 *   - [Edit-and-rerun]  -> reviewer-notes modal -> /execute    (long op, modal log)
 *   - [View files]      -> open sibling files/* in splits      (instant, no CLI)
 *
 * Spec invariants (architecture §1.2 / §3.2):
 *   - The plugin NEVER mutates `brief.md` directly. Reviewer notes flow
 *     through `/execute --reviewer-notes` argv. There is no plugin write
 *     path into review artifacts.
 *   - stderr is surfaced verbatim (truncated to 2000 chars). No silent
 *     failures, no defensive narration — the CLI/skill emits its own
 *     messages and we stream them.
 *   - No retries; one CLI invocation per click.
 *
 * Pure logic (slug derivation, trigger predicate, argv shape) lives in
 * `./briefActions.predicates.ts` so unit tests can import it without
 * resolving the `obsidian` package (architecture §1.1).
 */

import {
  App,
  MarkdownPostProcessorContext,
  Modal,
  Notice,
  setIcon,
  TFile,
  TFolder,
} from "obsidian";

import type GigaBrainPlugin from "../main";
import { getVaultBasePath } from "../settings";
import { runSkill } from "../bridge/claudeCode";
import { run as cnsRun } from "../cnsRunner";
import { RunSkillModal } from "../views/modal";
import {
  acceptArgs,
  deriveBriefSlug,
  editAndRerunArgs,
  isFirstSection,
  isUnderReviewsDir,
  rejectArgs,
  shouldInjectBriefBar,
} from "./briefActions.predicates";

/** Cap on how much stderr we paste into the retroactive log modal. */
const STDERR_TRUNCATE_CHARS = 2000;

/**
 * Resolve the reviews directory from settings with a defensive fallback to
 * the architectural baseline.
 */
function resolveReviewsDir(plugin: GigaBrainPlugin): string {
  const fromSettings = plugin.settings.reviewsDir;
  return fromSettings && fromSettings.length > 0
    ? fromSettings
    : "Brain/Reviews";
}

/**
 * Entry point registered in `main.ts` via `registerMarkdownPostProcessor`.
 * Same async-post-processor shape as `betActionBar`: read raw content for
 * frontmatter, validate the trigger, inject the bar synchronously after the
 * await.
 */
export async function briefActionBar(
  el: HTMLElement,
  ctx: MarkdownPostProcessorContext,
  plugin: GigaBrainPlugin,
): Promise<void> {
  const sourcePath = ctx.sourcePath;
  if (!sourcePath) return;

  const reviewsDir = resolveReviewsDir(plugin);
  if (!isUnderReviewsDir(sourcePath, reviewsDir)) return;

  const slug = deriveBriefSlug(sourcePath, reviewsDir);
  if (!slug) return;

  if (!isFirstSection(ctx.getSectionInfo(el))) return;

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

  if (!shouldInjectBriefBar(sourcePath, content, reviewsDir)) return;

  // Avoid duplicate bars on re-render.
  if (el.querySelector(":scope > .gigabrain-action-bar")) return;

  const bar = el.createDiv({ cls: "gigabrain-action-bar" });
  el.insertBefore(bar, el.firstChild);

  buildButton(bar, "Accept", "check-circle", () => {
    runShortReviewsOp(plugin, "Accept", acceptArgs(slug));
  });

  buildButton(bar, "Reject", "x-circle", () => {
    runShortReviewsOp(plugin, "Reject", rejectArgs(slug));
  });

  buildButton(bar, "Edit-and-rerun", "refresh-cw", () => {
    openReviewerNotesModal(plugin, slug);
  });

  buildButton(bar, "View files", "folder-open", () => {
    void openSiblingFiles(plugin, sourcePath);
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

// ---------------------------------------------------------------------------
// Short ops — Accept / Reject (Notice + retroactive modal log on failure)
// ---------------------------------------------------------------------------

/**
 * Run a short `cns reviews <verb> <slug>` op.
 *
 * Async-UX rule (architecture §3): short ops show a `Notice('running…')`
 * up front, then a `Notice('done')` or `Notice('failed: <stderr line 1>')`
 * with a "Show full output" button that opens a retroactive modal log.
 * stderr is truncated to 2000 chars per spec.
 */
function runShortReviewsOp(
  plugin: GigaBrainPlugin,
  verb: string,
  args: string[],
): void {
  const binPath = plugin.cnsBinaryPath;
  if (!binPath) {
    new Notice(
      "GigaBrain CNS: cns binary not configured. Open plugin settings.",
      6000,
    );
    return;
  }
  const cwd = getVaultBasePath(plugin.app);
  if (!cwd) {
    new Notice(
      "GigaBrain CNS: cannot resolve vault path (desktop only).",
      6000,
    );
    return;
  }

  const running = new Notice(`${verb}: running…`, 0);
  void cnsRun(binPath, args, { cwd })
    .then((result) => {
      running.hide();
      if (result.code === 0) {
        new Notice(`${verb}: done`);
        return;
      }
      // Surface stderr verbatim, truncated. First line preview goes in the
      // Notice; the full output is reachable via "Show full output".
      const trimmedStderr = (result.stderr ?? "").slice(
        0,
        STDERR_TRUNCATE_CHARS,
      );
      const firstLine = trimmedStderr.split("\n")[0]?.trim() || `exit ${result.code}`;
      surfaceFailure(plugin.app, `${verb} failed`, firstLine, {
        stdout: result.stdout ?? "",
        stderr: trimmedStderr,
        exitCode: result.code,
      });
    })
    .catch((err) => {
      running.hide();
      const msg = err instanceof Error ? err.message : String(err);
      surfaceFailure(plugin.app, `${verb} failed`, msg, {
        stdout: "",
        stderr: msg.slice(0, STDERR_TRUNCATE_CHARS),
        exitCode: -1,
      });
    });
}

/**
 * Show a failure Notice with a "Show full output" button that opens a
 * retroactive `LogModal` against captured stdout/stderr. Mirrors the
 * RunSkillModal log style for consistency, but does not stream — the run is
 * already done.
 */
function surfaceFailure(
  app: App,
  title: string,
  preview: string,
  capture: { stdout: string; stderr: string; exitCode: number },
): void {
  const notice = new Notice("", 10000);
  const frag = document.createDocumentFragment();
  frag.appendText(`${title}: ${preview}`);
  const btn = document.createElement("button");
  btn.style.marginLeft = "0.5em";
  btn.textContent = "Show full output";
  btn.addEventListener("click", (ev) => {
    ev.preventDefault();
    new LogModal(app, title, capture).open();
    notice.hide();
  });
  frag.appendChild(btn);
  notice.setMessage(frag);
}

// ---------------------------------------------------------------------------
// Long op — Edit-and-rerun (reviewer-notes modal -> /execute streaming modal)
// ---------------------------------------------------------------------------

/**
 * Open a small modal asking the leader for reviewer notes, then on submit
 * dispatch `/execute --bet <slug> --all --reviewer-notes <notes>` through
 * the bridge in a streaming `RunSkillModal`.
 *
 * Per spec invariant: the plugin never writes to brief.md. Notes flow only
 * via argv into the skill, which decides what (if anything) to record.
 */
function openReviewerNotesModal(plugin: GigaBrainPlugin, slug: string): void {
  const cwd = getVaultBasePath(plugin.app);
  if (!cwd) {
    new Notice(
      "GigaBrain CNS: cannot resolve vault path (desktop only).",
      6000,
    );
    return;
  }
  new ReviewerNotesModal(plugin.app, slug, (notes) => {
    const args = editAndRerunArgs(slug, notes);
    const modal = new RunSkillModal(
      plugin.app,
      `Edit-and-rerun ${slug}`,
      (signal) => runSkill("execute", args, { cwd, signal }),
    );
    modal.open();
  }).open();
}

/**
 * Lightweight modal: textarea + Run / Cancel buttons. On Run, calls back
 * with the textarea's contents (empty string allowed — the skill decides
 * what to do with that).
 */
class ReviewerNotesModal extends Modal {
  private slug: string;
  private onSubmit: (notes: string) => void;

  constructor(app: App, slug: string, onSubmit: (notes: string) => void) {
    super(app);
    this.slug = slug;
    this.onSubmit = onSubmit;
  }

  onOpen(): void {
    const { contentEl } = this;
    contentEl.empty();
    contentEl.addClass("gigabrain-edit-rerun-modal");

    contentEl.createEl("h3", { text: `Edit-and-rerun: ${this.slug}` });
    contentEl.createEl("p", {
      cls: "setting-item-description",
      text:
        "Notes are passed to /execute via --reviewer-notes. Brief.md is not modified by the plugin.",
    });

    const textarea = contentEl.createEl("textarea", {
      attr: { rows: "6", placeholder: "Reviewer notes" },
    });

    const buttons = contentEl.createDiv({ cls: "gigabrain-modal-buttons" });
    const runBtn = buttons.createEl("button", {
      text: "Run",
      cls: "mod-cta",
    });
    const cancelBtn = buttons.createEl("button", { text: "Cancel" });

    runBtn.addEventListener("click", (ev) => {
      ev.preventDefault();
      const notes = (textarea as unknown as { value?: string }).value ?? "";
      this.close();
      this.onSubmit(notes);
    });

    cancelBtn.addEventListener("click", (ev) => {
      ev.preventDefault();
      this.close();
    });
  }

  onClose(): void {
    this.contentEl.empty();
  }
}

// ---------------------------------------------------------------------------
// View files — open sibling files/ contents in new splits
// ---------------------------------------------------------------------------

/**
 * Open every file under the brief's sibling `files/` directory in new
 * Obsidian splits. Skips silently if the directory is empty or missing
 * (per spec).
 *
 * `app.workspace.openLinkText(linkText, sourcePath, true)` opens in a new
 * leaf — passing `sourcePath` resolves the link relative to the brief.
 */
async function openSiblingFiles(
  plugin: GigaBrainPlugin,
  briefPath: string,
): Promise<void> {
  const briefDir = briefPath.substring(0, briefPath.lastIndexOf("/"));
  if (!briefDir) return;
  const filesDir = `${briefDir}/files`;

  const folder = plugin.app.vault.getAbstractFileByPath(filesDir);
  if (!(folder instanceof TFolder)) {
    // No files/ dir — skip silently per spec.
    return;
  }

  const children = collectFiles(folder);
  if (children.length === 0) return;

  for (const child of children) {
    await plugin.app.workspace.openLinkText(child.path, briefPath, true);
  }
}

/** Recursively gather every TFile under a folder. */
function collectFiles(folder: TFolder): TFile[] {
  const out: TFile[] = [];
  const walk = (f: TFolder): void => {
    for (const child of f.children) {
      if (child instanceof TFile) {
        out.push(child);
      } else if (child instanceof TFolder) {
        walk(child);
      }
    }
  };
  walk(folder);
  return out;
}

// ---------------------------------------------------------------------------
// Retroactive log modal (post-failure)
// ---------------------------------------------------------------------------

/**
 * Display captured stdout/stderr + exit code in a styled `<pre>`. Mirrors
 * RunSkillModal's visual language so leaders see the same surface for both
 * streaming and post-mortem views, but does NOT consume an iterable — the
 * run is already finished by the time this opens.
 */
class LogModal extends Modal {
  private title: string;
  private capture: { stdout: string; stderr: string; exitCode: number };

  constructor(
    app: App,
    title: string,
    capture: { stdout: string; stderr: string; exitCode: number },
  ) {
    super(app);
    this.title = title;
    this.capture = capture;
  }

  onOpen(): void {
    const { contentEl } = this;
    contentEl.empty();

    const header = contentEl.createDiv({ cls: "gigabrain-modal-header" });
    header.createEl("h3", { text: this.title });

    const buttons = header.createDiv({ cls: "gigabrain-modal-buttons" });
    const closeBtn = buttons.createEl("button", { text: "Close" });
    closeBtn.addEventListener("click", () => this.close());

    const log = contentEl.createEl("pre", { cls: "gigabrain-modal-log" });
    if (this.capture.stdout) {
      const span = log.createSpan({ cls: "stdout" });
      span.setText(this.capture.stdout);
    }
    if (this.capture.stderr) {
      const span = log.createSpan({ cls: "stderr" });
      span.setText(this.capture.stderr);
    }

    const footer = contentEl.createDiv({ cls: "gigabrain-modal-footer" });
    footer.setText(`Exit code: ${this.capture.exitCode}`);
  }

  onClose(): void {
    this.contentEl.empty();
  }
}
