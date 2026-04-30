# Getting started with CNS

This walkthrough takes you from zero to a resolved conflict in under 10 minutes.

## 1. Install

```bash
pip install cns
```

You also need the `cns` skills installed in Claude Code (or your preferred agent). See [installing skills](#installing-skills) below.

## 2. Bootstrap your vault

```bash
cd /path/to/your/vault
cns bootstrap
```

This creates a minimal default config. For interactive setup with a config wizard, use the `/cns-bootstrap` Claude Code skill instead.

You can also choose a richer preset with `--preset`:

```bash
cns bootstrap --preset solo-founder    # 7-role solo-founder config
cns bootstrap --preset engineering-lead
```

This produces:
- `.cns/config.yaml` — your CNS configuration
- `Brain/Bets/` — empty bets directory
- `Brain/CONFLICTS.md` — empty conflicts queue

## 3. Write your first bet

```bash
cp /path/to/cns/templates/bet.md.template Brain/Bets/bet_first.md
$EDITOR Brain/Bets/bet_first.md
```

Fill in the frontmatter and body sections. The most important field is `kill_criteria` — what observable signal would flip this bet? If you can't articulate it yet, leave the default `"unspecified — needs sparring"` and the detector will flag it for you.

## 4. Run the unified walk

In Claude Code (or your agent):

```
/cns
```

That's it — one invocation. The `/cns` skill detects whether your bet is newer than the index, runs `cns reindex` if so, runs detection, and then chains into `/spar` to walk any conflicts. You read your bet in Obsidian and resolve in Claude Code; you never have to touch the terminal in between.

If you left `kill_criteria` as the default, the spar walk will surface it as a conflict — pick `[e] Edit` and fill it in. That conflict drops out of the queue and your bet's `last_reviewed` updates.

### What if I want to run the steps individually?

You can. The unified walk is a router on top of these primitives:

- `cns reindex` — regenerate `Brain/Bets/BETS.md` from active bet files
- `cns reindex --check` — exit 1 if any bet is newer than the index (used internally by `/cns`)
- `cns detect` (or `/cns-detect`) — write `Brain/CONFLICTS.md`
- `/spar` — walk the conflicts queue (and review queue, once `/execute` is enabled)

Most users only ever run `/cns`.

## 5. (Optional) Wire into automation

If you have a daily report cron, see [wiring-into-automation.md](wiring-into-automation.md) for how to add `cns detect` as a post-report step so conflicts surface in your daily TL;DR automatically.

## Installing skills

The CNS skills (`cns`, `cns-bootstrap`, `cns-detect`, `spar`) live in `skills/` in this repo. Copy them into your Claude Code skills directory or symlink them. Exact procedure varies by Claude Code version.
