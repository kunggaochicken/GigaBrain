import { defineConfig } from "vitest/config";
import { resolve } from "path";

/**
 * The `obsidian` npm package ships only TypeScript declarations
 * (`main: ""` in its package.json), which Vite refuses to resolve at test
 * time. Tests that exercise modules importing `obsidian` (e.g. `views/modal.ts`)
 * need a runtime stub. We point the alias at a tiny shim under
 * `src/__tests__/`; tests that need richer behavior can still `vi.mock`
 * over the top of it.
 */
export default defineConfig({
  resolve: {
    alias: {
      obsidian: resolve(__dirname, "src/__tests__/__stubs__/obsidian.ts"),
    },
  },
});
