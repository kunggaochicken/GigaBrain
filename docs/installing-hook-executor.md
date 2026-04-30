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
