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

## 4. Regenerate the index

```bash
cns reindex
```

Open `Brain/Bets/BETS.md` to see your bet listed under its owner role.

## 5. Run detection

```bash
cns detect
```

If you left `kill_criteria` as the default, you'll see one conflict in `Brain/CONFLICTS.md` flagging it for sparring. That's expected — it's the system telling you "you committed to a bet but didn't say what would change your mind."

## 6. Spar

In Claude Code (or your agent):

```
/spar
```

The skill walks you through your conflicts. Pick `[e] Edit` and fill in `kill_criteria` for your bet. Done — that conflict drops out of the queue and your bet's `last_reviewed` updates.

## 7. (Optional) Wire into automation

If you have a daily report cron, see [wiring-into-automation.md](wiring-into-automation.md) for how to add `cns detect` as a post-report step so conflicts surface in your daily TL;DR automatically.

## Installing skills

The CNS skills (`cns`, `cns-bootstrap`, `cns-detect`, `spar`) live in `skills/` in this repo. Copy them into your Claude Code skills directory or symlink them. Exact procedure varies by Claude Code version.
