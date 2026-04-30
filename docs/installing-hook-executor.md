# Installing the /execute PreToolUse hook (v0.3, issue #30)

`/execute` dispatches role-scoped agents that — without enforcement —
rely on the agent reading its system prompt and staying inside the
approved scope. v0.3 ships a Claude Code **PreToolUse hook** that turns
prompt-enforcement into machine-enforcement.

When the hook is installed:

- `Edit` / `Write` outside the bet's staging directory is **denied**.
- `WebFetch` to a host not in the role's `tools.web_allowlist` is **denied**.
- `WebFetch` when `tools.web: false` is **denied**.
- `Bash` commands not matching `tools.bash_allowlist` are **denied**.

When no `/execute` run is in flight, the hook is in **open mode** —
calls pass through. The hook is safe to install globally.

## Install

1. Make sure the `cns` package is on `PATH`. After `pip install -e .`
   (or `pip install cns`), you should see:

   ```
   $ which cns-hook-pretooluse
   /.../bin/cns-hook-pretooluse
   ```

2. Merge the snippet from `templates/claude-settings.hook.json.template`
   into your Claude Code settings file. Either:

   - **Per-project**: `<project-root>/.claude/settings.json` — applies to
     this checkout only.
   - **User-wide**: `~/.claude/settings.json` — applies to every Claude
     Code session you run.

   Minimal settings file:

   ```json
   {
     "hooks": {
       "PreToolUse": [
         {
           "matcher": "Edit|Write|MultiEdit|NotebookEdit|WebFetch|WebSearch|Bash",
           "hooks": [
             {
               "type": "command",
               "command": "cns-hook-pretooluse"
             }
           ]
         }
       ]
     }
   }
   ```

3. Verify the hook fires by piping a synthetic tool call to it:

   ```bash
   echo '{"hook_event_name":"PreToolUse","tool_name":"Bash","tool_input":{"command":"echo hi"}}' \
     | cns-hook-pretooluse
   # -> {"hookSpecificOutput": {"permissionDecision": "allow", ...}}
   #    (open mode, since no /execute run is active)
   ```

## How active-bet resolution works

At hook time, the executor figures out which bet is active by checking,
in order:

1. **`$CNS_ACTIVE_BET`** — env var naming the slug. Pair with
   `$CNS_VAULT_ROOT` to skip vault-walk.
2. **Sentinel file** at `<vault>/.cns/.agent-hooks/.active` — JSON
   record `{"slug": "...", "vault_root": "..."}`. Written by
   `cns hook-active set <slug>`, cleared by `cns hook-active clear`.
   The `/execute` skill manages this file across each per-bet Agent
   invocation.
3. **Auto-detect**: if exactly one
   `<vault>/.cns/.agent-hooks/<slug>.json` descriptor exists, treat
   that as active (covers single-bet runs without explicit marking).

If none of those resolve, the hook returns `allow` and gets out of the
way.

### Fail-closed on explicit-but-unresolvable slugs

`$CNS_ACTIVE_BET` is the user's (or dispatcher's) explicit statement
that a bet is active. If the env var is set but the descriptor at
`<vault>/.cns/.agent-hooks/<slug>.json` is missing or unreadable, the
hook **denies all gated tool calls** instead of silently falling through
to open mode. The deny message names the missing slug and the expected
descriptor path so the user can fix the underlying problem (or run
`cns hook-active clear` to return to open mode). Read-style tools
(`Read`, `Glob`, `Grep`) stay open even in this state — only writes and
external calls are gated. This is the safer default: an in-flight
`/execute` run that loses its descriptor should refuse tools, not
bypass enforcement (issue #30 P1).

### `cns hook-active clear` and the `.cleared` tombstone

Running `cns hook-active clear` removes the `.active` sentinel **and**
writes an empty `.cleared` tombstone next to it. The auto-detect path
checks for the tombstone and bails (returns open mode) when it's
present, so a leftover `<vault>/.cns/.agent-hooks/<slug>.json`
descriptor cannot silently re-activate enforcement after the user
explicitly cleared. The next `cns hook-active set <slug>` removes the
tombstone, and explicit `$CNS_ACTIVE_BET` env-var resolution is
unaffected by it (the tombstone only suppresses auto-detect, not
explicit per-process intent — issue #30 P2).

## What the hook does NOT block

- **`Read` / `Glob` / `Grep`** — `/execute` is about scoping writes and
  external calls, not reads. Future work may add a read-allowlist;
  today the agent's system prompt is the only constraint there.
- **Anything outside an `/execute` dispatch** — the open-mode default
  means casual editing, debugging, and other Claude Code workflows
  are unaffected.

## Troubleshooting

- **Every tool call denied with "missing staging_dir"**: the descriptor
  at `<vault>/.cns/.agent-hooks/<slug>.json` is malformed or stale. Re-run
  `cns execute` to regenerate it.
- **Edits outside staging silently allowed**: the hook isn't actually
  installed. Run `which cns-hook-pretooluse` and check that
  `.claude/settings.json` parses (Claude Code will log a parse error
  but still proceed without the hook).
- **`/execute` run interferes with parallel Claude Code sessions**: the
  sentinel file is process-global. If you need per-session scoping,
  set `$CNS_ACTIVE_BET` directly in the dispatching shell instead of
  relying on the sentinel.
