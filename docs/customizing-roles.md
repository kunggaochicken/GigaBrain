# Customizing your role roster

CNS doesn't enforce a specific C-suite roster. The `roles` field in `.cns/config.yaml` is whatever set of role IDs and display names you want.

## Presets that ship in `examples/`

- **`config-solo-founder.yaml`** — 7-role C-suite (CEO, CTO, CSO, CMO, CPO, CLO, CFO). Default for solo founders.
- **`config-engineering-lead.yaml`** — 4-role roster (engineer, manager, designer, PM). For engineering leads who want to track strategic bets without C-suite branding.

## Writing your own

```yaml
roles:
  - id: founder
    name: Founder
  - id: tech_lead
    name: Tech Lead
  - id: ops
    name: Operations
```

Constraints:
- `id` values must be unique
- `id` is what goes in each bet's `owner:` field
- `name` is the display name in `BETS.md` and `CONFLICTS.md`

## Adding/removing roles after bets exist

If you rename `cto` to `engineering`, all existing bets with `owner: cto` will fail validation. Either:
1. Edit each bet's `owner:` field (find/replace works)
2. Keep the old `id` in your config under the new `name`:
   ```yaml
   - id: cto
     name: Engineering
   ```
