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
