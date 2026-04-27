---
name: role-setup
description: Add, edit, or delete roles in .cns/config.yaml. Loads from templates/roles/ for common roles (CTO, CMO, CPO, etc.) and walks the user through workspace paths, bash allowlist, and persona. Use when the user wants to add a new C-suite role, an engineer/marketer/designer subordinate, or modify an existing role's workspaces or persona.
---

# /role-setup — Add, edit, or delete a role

`/role-setup` is the conversational front door for the `roles:` section of `.cns/config.yaml`. It uses templates from `templates/roles/` so the user does not have to remember the schema.

## When to use

- User says: "add a role", "set up the CTO", "add an engineer", "edit the CMO's workspaces"
- User has just bootstrapped CNS and is filling in the org structure
- The org grows (a CTO needs to spawn VPs, etc.)

## Procedure

1. **Locate the vault.** Walk up for `.cns/config.yaml`.

2. **Ask: add / edit / delete?**

3. **If add:**

   a. **"Pick a template:"** — multiple choice listing every file in `templates/roles/` (CEO, CTO, CMO, CPO, Chief Scientist, VP of Engineering, Engineer, Marketing Lead, Designer, plus `[blank]`).

   b. Load the chosen template via `yaml.safe_load`. For `[blank]`, start with `{id: "", name: "", reports_to: null, workspaces: [], tools: {bash_allowlist: [], web: false}, persona: ""}`.

   c. **Walk fields, prefilled from template:**
      - `id` (must be unique against existing role ids; reject collisions)
      - `name`
      - `reports_to` — multiple choice from existing role ids (or `null` if this is the first/root role; reject `null` if a root already exists)
      - `workspaces` — for each entry in template, ask for the actual path (replace `<YOUR_CODE_REPO>` placeholders); ask if user wants to add more
      - `tools.bash_allowlist` — show defaults, ask if user wants to add or remove
      - `persona` — show default, ask if user wants to edit

   d. **Append to `.cns/config.yaml`** using `ruamel.yaml` (round-trip mode) so existing comments and ordering are preserved:
      ```python
      from ruamel.yaml import YAML
      yaml = YAML()
      yaml.preserve_quotes = True
      with open(cfg_path) as f:
          data = yaml.load(f)
      data["roles"].append(new_role_dict)
      with open(cfg_path, "w") as f:
          yaml.dump(data, f)
      ```

   e. **Re-validate the full config** by running `cns validate`. If validation fails (e.g., a cycle was introduced), print the error and offer to revert.

4. **If edit:**

   a. Multiple choice: pick from existing roles.

   b. Walk each field prefilled with current value; user can keep or change.

   c. Write back via the same `ruamel.yaml` round-trip.

   d. Re-validate.

5. **If delete:**

   a. Multiple choice: pick from existing roles.

   b. **Refuse if any active bet's owner matches** the role id — show the offending bet filenames and tell the user to reassign or close those bets first.

   c. **Refuse if any other role's `reports_to` matches** the role id — show the dangling subordinates and tell the user to either delete them first or re-parent them.

   d. Otherwise, remove from `data["roles"]` and write back.

6. **Final action.** Print the updated role tree (e.g., `cns roles list`).

## Constraints

- NEVER write directly to `.cns/config.yaml` with `yaml.safe_dump` — use `ruamel.yaml` round-trip so comments survive.
- NEVER allow two roles with the same `id`.
- NEVER allow a delete that would create dangling `reports_to` or orphan active bets.
- When `reports_to` is set to a non-existent id, surface a clear error before writing.
- The first role added must have `reports_to: null` (the root). After that, additional roots are forbidden — `cns validate` will catch this; this skill should ask `reports_to` and reject `null` once a root exists.
