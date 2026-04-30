/**
 * Test-time stub for the `obsidian` npm package, which ships only
 * TypeScript declarations (its `main` field is empty) and therefore is not
 * resolvable by Vite at runtime. We map the bare specifier "obsidian" to
 * this file via `vitest.config.ts`. Production code is untouched: the real
 * `obsidian` runtime is provided by the host application.
 *
 * The shim only models the surface that `views/modal.ts` reaches for:
 *   - `Modal` base class with an `app`, `contentEl`, and `open`/`close`
 *     dispatch into `onOpen`/`onClose`.
 *   - `setIcon` (no-op) and `App` (structural placeholder).
 *
 * Tests can `vi.mock("obsidian", ...)` to override this if they need
 * richer behavior; the alias just gives Vite something to resolve to.
 */

class FakeEl {
  children: unknown[] = [];
  scrollTop = 0;
  scrollHeight = 0;
  disabled = false;

  empty(): void {
    this.children.length = 0;
  }
  setText(_: string): void {
    /* no-op */
  }
  createDiv(_opts?: unknown): FakeEl {
    const c = new FakeEl();
    this.children.push(c);
    return c;
  }
  createEl(_tag: string, _opts?: unknown): FakeEl {
    const c = new FakeEl();
    this.children.push(c);
    return c;
  }
  createSpan(_opts?: unknown): FakeEl {
    const c = new FakeEl();
    this.children.push(c);
    return c;
  }
  appendChild(c: unknown): void {
    this.children.push(c);
  }
  addEventListener(_event: string, _handler: () => void): void {
    /* no-op */
  }
}

export class Modal {
  app: unknown;
  contentEl: FakeEl = new FakeEl();
  containerEl: FakeEl = new FakeEl();

  constructor(app: unknown) {
    this.app = app;
  }

  open(): void {
    const self = this as unknown as { onOpen?: () => void };
    self.onOpen?.();
  }

  close(): void {
    const self = this as unknown as { onClose?: () => void };
    self.onClose?.();
  }
}

export class App {}

export function setIcon(_el: unknown, _name: string): void {
  /* no-op */
}

// ---- Stubs reached for transitively via `settings.ts` import chain ----
// `processors/conflictsActions.ts` imports `getVaultBasePath` from
// `../settings`, which itself extends `PluginSettingTab` and references
// `FileSystemAdapter`. Tests don't exercise the settings panel, but the
// module needs to evaluate without throwing on class-resolution.

export class PluginSettingTab {
  app: unknown;
  plugin: unknown;
  containerEl: FakeEl = new FakeEl();
  constructor(app: unknown, plugin: unknown) {
    this.app = app;
    this.plugin = plugin;
  }
  display(): void {
    /* no-op */
  }
  hide(): void {
    /* no-op */
  }
}

export class Setting {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  controlEl: any = new FakeEl();
  constructor(_containerEl: unknown) {
    /* no-op */
  }
  setName(_name: string): this {
    return this;
  }
  setDesc(_desc: string): this {
    return this;
  }
  addText(_cb: (t: unknown) => void): this {
    return this;
  }
  addToggle(_cb: (t: unknown) => void): this {
    return this;
  }
  then(_cb: (s: this) => void): this {
    return this;
  }
}

export class FileSystemAdapter {
  getBasePath(): string {
    return "";
  }
}

export class Notice {
  constructor(_message: string, _timeout?: number) {
    /* no-op */
  }
}

export class TFile {}

export class TAbstractFile {}

export class WorkspaceLeaf {}
