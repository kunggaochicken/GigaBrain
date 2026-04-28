"""CLI entry points: bootstrap, validate, reindex, detect, execute, reviews, roles."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import click

from cns.config import ConfigInvalidError, ConfigNotFoundError, find_vault_root, load_config
from cns.conflicts import (
    merge_detected,
    parse_conflicts_file,
    render_conflicts_file,
)
from cns.daily_report import append_conflicts_section, inject_tldr_line
from cns.detector import detect_conflicts
from cns.execute import (
    NoExecutionConfigError,
    build_agent_envelope,
    build_dispatch_queue,
)
from cns.index import render_bets_index
from cns.models import BetStatus
from cns.reviews import (
    ReviewNotFoundError,
    accept_review,
    list_pending_reviews,
    reject_review,
    reviews_root,
)
from cns.roles import RoleTreeError, find_root_role
from cns.signals import GitCommitsSignal, GitHubPRsSignal, VaultDirSignal


def _load_vault(vault: Path | None):
    root = vault or find_vault_root(Path.cwd())
    if root is None:
        raise click.ClickException("no vault root found (no .cns/config.yaml in cwd or ancestors)")
    try:
        cfg = load_config(root / ".cns/config.yaml")
    except (ConfigNotFoundError, ConfigInvalidError) as e:
        raise click.ClickException(str(e)) from e
    return root, cfg


def _build_signal_sources(cfg):
    out = []
    for s in cfg.signal_sources:
        if s.kind == "vault_dir":
            out.append(VaultDirSignal(path=s.path))
        elif s.kind == "git_commits":
            out.append(GitCommitsSignal(repos=s.repos or []))
        elif s.kind == "github_prs":
            out.append(GitHubPRsSignal(repos=s.repos or [], auth=s.auth or "gh_cli"))
    return out


@click.group()
def cli():
    """CNS: Central Nervous System for atomized strategic bets."""


@cli.command()
@click.option(
    "--vault", type=click.Path(path_type=Path), default=None, help="Vault root (default: cwd)"
)
@click.option(
    "--preset",
    type=click.Choice(["solo-founder", "engineering-lead", "minimal"]),
    default="minimal",
    help="Config preset to use",
)
def bootstrap(vault, preset):
    """Initialize CNS in a vault with a default config (use --preset for richer presets)."""
    root = vault or Path.cwd()
    config_dir = root / ".cns"
    config_path = config_dir / "config.yaml"
    if config_path.exists():
        raise click.ClickException(f"config already exists at {config_path}")
    config_dir.mkdir(parents=True, exist_ok=True)

    pkg_root = Path(__file__).resolve().parent.parent
    if preset == "solo-founder":
        src = pkg_root / "examples/config-solo-founder.yaml"
    elif preset == "engineering-lead":
        src = pkg_root / "examples/config-engineering-lead.yaml"
    else:
        src = pkg_root / "templates/config.yaml.template"

    if not src.exists():
        raise click.ClickException(f"preset/template not found at {src}")
    config_path.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")

    cfg = load_config(config_path)
    bets_dir = root / cfg.brain.bets_dir
    bets_dir.mkdir(parents=True, exist_ok=True)
    conflicts_path = root / cfg.brain.conflicts_file
    conflicts_path.parent.mkdir(parents=True, exist_ok=True)
    if not conflicts_path.exists():
        conflicts_path.write_text("# Open Conflicts\n", encoding="utf-8")

    click.echo(f"CNS bootstrapped at {root}")
    click.echo(f"  config: {config_path}")
    click.echo(f"  bets dir: {bets_dir}")
    click.echo(f"  conflicts: {conflicts_path}")
    click.echo(
        "Next: write a bet (cp templates/bet.md.template <bets_dir>/bet_<slug>.md), "
        "then `cns reindex` and `cns detect`."
    )


@cli.command()
@click.option(
    "--vault",
    type=click.Path(path_type=Path, exists=True),
    default=None,
    help="Vault root (auto-detected if omitted)",
)
def validate(vault):
    """Validate config and bet files."""
    try:
        root, cfg = _load_vault(vault)
    except (ConfigNotFoundError, ConfigInvalidError, click.ClickException) as e:
        raise click.ClickException(str(e)) from e
    bets_dir = root / cfg.brain.bets_dir
    n = 0
    errors = []
    for path in sorted(bets_dir.glob("bet_*.md")):
        try:
            from cns.bet import load_bet

            load_bet(path)
            n += 1
        except Exception as e:
            errors.append(f"{path.name}: {e}")
    if errors:
        click.echo("FAIL")
        for e in errors:
            click.echo(f"  {e}")
        raise click.ClickException(f"{len(errors)} invalid bet(s)")
    click.echo(f"OK: {n} bet(s) parsed cleanly, config valid.")


@cli.command()
@click.option("--vault", type=click.Path(path_type=Path, exists=True), default=None)
def reindex(vault):
    """Regenerate BETS.md from active bet files."""
    root, cfg = _load_vault(vault)
    bets_dir = root / cfg.brain.bets_dir
    bets_with_paths = []
    for path in sorted(bets_dir.glob("bet_*.md")):
        try:
            from cns.bet import load_bet

            bet = load_bet(path)
        except Exception as e:
            click.echo(f"warning: skipping malformed bet {path.name}: {e}", err=True)
            continue
        if bet.status == BetStatus.ACTIVE:
            bets_with_paths.append((bet, path.name))
    text = render_bets_index(bets_with_paths, cfg.roles)
    out = root / cfg.brain.bets_index
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text + "\n", encoding="utf-8")
    click.echo(f"Wrote {out} ({len(bets_with_paths)} active bets)")


@cli.command()
@click.option("--vault", type=click.Path(path_type=Path, exists=True), default=None)
@click.option("--today", default=None, help="Override today's date (YYYY-MM-DD), for testing.")
def detect(vault, today):
    """Run conflict detection. Writes CONFLICTS.md and (optionally) updates daily note."""
    root, cfg = _load_vault(vault)
    today_d = date.fromisoformat(today) if today else date.today()

    bets_dir = root / cfg.brain.bets_dir
    bets_with_paths = []
    for path in sorted(bets_dir.glob("bet_*.md")):
        try:
            from cns.bet import load_bet

            bet = load_bet(path)
        except Exception as e:
            click.echo(f"warning: skipping malformed bet {path.name}: {e}", err=True)
            continue
        if bet.status == BetStatus.ACTIVE:
            bets_with_paths.append((bet, path.name))

    sources = _build_signal_sources(cfg)
    signals = []
    for src in sources:
        signals.extend(src.collect(vault_root=root, window_hours=cfg.detection.window_hours))

    detected = detect_conflicts(bets_with_paths, signals, cfg, today_d)

    conflicts_path = root / cfg.brain.conflicts_file
    existing = parse_conflicts_file(conflicts_path)

    import subprocess

    modified_today: set[str] = set()
    try:
        result = subprocess.run(
            [
                "git",
                "log",
                f"--since={cfg.detection.window_hours} hours ago",
                "--name-only",
                "--pretty=format:",
                "--",
                cfg.brain.bets_dir,
            ],
            cwd=root,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        result = None
    if result and result.returncode == 0:
        for line in result.stdout.splitlines():
            line = line.strip()
            if line.startswith(cfg.brain.bets_dir + "/"):
                modified_today.add(line.removeprefix(cfg.brain.bets_dir + "/"))

    merged = merge_detected(existing, detected, modified_today)
    conflicts_path.parent.mkdir(parents=True, exist_ok=True)
    conflicts_path.write_text(
        render_conflicts_file(merged, cfg.roles, today_d) + "\n",
        encoding="utf-8",
    )
    click.echo(f"Wrote {conflicts_path} ({len(merged)} conflicts)")

    dr = cfg.automation.daily_report
    if dr.daily_note_dir:
        note = root / dr.daily_note_dir / f"{today_d.isoformat()}.md"
        if note.exists():
            if dr.inject_tldr_line and merged:
                oldest = max((today_d - c.first_detected).days for c in merged)
                inject_tldr_line(note, len(merged), oldest)
            append_conflicts_section(
                note,
                merged,
                today_d,
                conflicts_file_path=cfg.brain.conflicts_file,
            )
            click.echo(f"Updated daily note {note}")


@cli.command()
@click.option("--vault", type=click.Path(path_type=Path, exists=True), default=None)
@click.option(
    "--bet",
    "bet_filter",
    default=None,
    help="Run only this bet slug (without bet_ prefix or .md).",
)
@click.option(
    "--owner",
    "owner_filter",
    default=None,
    help="Run only bets owned by this role id.",
)
@click.option(
    "--all",
    "include_pending",
    is_flag=True,
    default=False,
    help="Re-dispatch bets that already have a pending review (replaces the staged dir).",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Print plan; do not write hook configs.",
)
@click.argument("init_subcmd", required=False, type=click.Choice(["init"]))
def execute(vault, bet_filter, owner_filter, include_pending, dry_run, init_subcmd):
    """Build the dispatch plan for /execute (or run `init` to scaffold config)."""
    if init_subcmd == "init":
        _execute_init(vault)
        return

    root, cfg = _load_vault(vault)
    try:
        plan = build_dispatch_queue(
            vault_root=root,
            cfg=cfg,
            bet_filter=bet_filter,
            owner_filter=owner_filter,
            include_pending=include_pending,
        )
    except NoExecutionConfigError as e:
        raise click.ClickException(
            f"{e}. Run `cns execute init` to scaffold execution config."
        ) from e

    if not plan:
        click.echo("No active bets matched the filter.")
        return

    dispatched = [i for i in plan if i.dispatch]
    skipped = [i for i in plan if not i.dispatch]
    click.echo(f"Plan: {len(dispatched)} to dispatch, {len(skipped)} skipped.\n")
    for item in plan:
        if item.dispatch:
            click.echo(f"  [DISPATCH] bet_{item.bet_slug}.md  owner={item.owner}")
        else:
            click.echo(
                f"  [SKIP {item.skip_reason.value}] bet_{item.bet_slug}.md  owner={item.owner}"
            )

    if dry_run:
        click.echo("\n(dry-run; no hook configs written, no agents dispatched)")
        return

    click.echo("\nWriting per-bet envelopes:")
    for item in dispatched:
        env = build_agent_envelope(item=item, vault_root=root, cfg=cfg)
        click.echo(f"  -> {env['hook_config_path']}")
    click.echo(
        "\nEnvelopes written. The /execute skill (in Claude Code) reads these "
        "and dispatches agents via the Agent tool."
    )


def _execute_init(vault):
    """Add an execution{} block to .cns/config.yaml (idempotent)."""
    root = vault or Path.cwd()
    cfg_path = root / ".cns/config.yaml"
    if not cfg_path.exists():
        raise click.ClickException(f"no config at {cfg_path}")
    text = cfg_path.read_text(encoding="utf-8")
    if "\nexecution:" in text or text.startswith("execution:"):
        click.echo("execution{} block already present.")
        return

    cfg = load_config(cfg_path)
    try:
        root_role = find_root_role(cfg.roles)
    except RoleTreeError:
        if not cfg.roles:
            raise click.ClickException("config has no roles defined") from None
        root_role = cfg.roles[0]

    block = (
        "\nexecution:\n"
        "  reviews_dir: Brain/Reviews\n"
        f"  top_level_leader: {root_role.id}\n"
        "  default_filter: pending\n"
        "  artifact_max_files: 50\n"
        "  # Set true to use Brain/Reviews/<leader-id>/<bet>/ instead of\n"
        "  # Brain/Reviews/<bet>/. Required once your org has more than one\n"
        "  # leader (e.g. CTO with VPs). See `cns vault migrate-reviews`.\n"
        "  reviews_dir_per_leader: false\n"
    )
    new_text = text.rstrip() + block

    # Validate the prospective config BEFORE writing. Adding `execution:`
    # opts the role tree into strict validation (see Config._valid_role_tree),
    # so a flat roles list that was tolerated before would now be rejected.
    # Failing after the write would leave the user with a bricked config.
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8") as tmp:
        tmp.write(new_text)
        tmp_path = Path(tmp.name)
    try:
        load_config(tmp_path)
    except ConfigInvalidError as e:
        msg = str(e).replace(str(tmp_path), str(cfg_path))
        hint = ""
        if "multiple roots" in msg:
            # Extract the offending ids if present so the hint is concrete.
            import re

            m = re.search(r"multiple roots:\s*([^\[\]]+?)(?:\s*\[|$)", msg)
            ids_str = m.group(1).strip() if m else ""
            non_leader = ""
            if ids_str:
                ids = [i.strip() for i in ids_str.split(",") if i.strip()]
                non_leader = ", ".join(i for i in ids if i != root_role.id)
            hint = (
                "\n\nHint: an execution-aware config requires exactly one root role "
                "(reports_to: null). Pick a leader (likely '"
                f"{root_role.id}') and set `reports_to: {root_role.id}` on the other "
                f"roles ({non_leader or 'all non-leader roles'}) in "
                f"{cfg_path}, then re-run `cns execute init`."
            )
        elif "cycle" in msg or "dangling" in msg:
            hint = (
                "\n\nHint: fix the role tree in "
                f"{cfg_path} (each non-leader role's `reports_to` must reference an "
                "existing role id; exactly one role must have `reports_to: null` and "
                "the graph must be acyclic), then re-run `cns execute init`."
            )
        raise click.ClickException(
            f"refusing to write execution block — resulting config would be invalid:\n  {msg}{hint}"
        ) from e
    finally:
        tmp_path.unlink(missing_ok=True)

    cfg_path.write_text(new_text, encoding="utf-8")
    (root / "Brain/Reviews").mkdir(parents=True, exist_ok=True)
    click.echo(f"Added execution{{}} block; top_level_leader='{root_role.id}'.")


@cli.group()
def reviews():
    """List, accept, and reject pending /execute reviews."""


@reviews.command("list")
@click.option("--vault", type=click.Path(path_type=Path, exists=True), default=None)
@click.option(
    "--leader",
    "leader_id",
    default=None,
    help=(
        "Leader id whose queue to walk. Defaults to execution.top_level_leader. "
        "Only meaningful when execution.reviews_dir_per_leader is true."
    ),
)
def reviews_list(vault, leader_id):
    root, cfg = _load_vault(vault)
    if cfg.execution is None:
        raise click.ClickException("no execution config — run `cns execute init` first")
    pending = list_pending_reviews(reviews_root(cfg, root, leader_id=leader_id))
    if not pending:
        click.echo("0 pending reviews.")
        return
    click.echo(f"{len(pending)} pending review(s):\n")
    for slug, brief in pending:
        marker = " [proposed_closure]" if brief.proposed_closure else ""
        click.echo(f"  {slug}  bet={brief.bet}  owner={brief.owner}{marker}")


@reviews.command("accept")
@click.argument("slug")
@click.option("--vault", type=click.Path(path_type=Path, exists=True), default=None)
@click.option("--leader", "leader_id", default=None, help="Leader id (per-leader layout only).")
def reviews_accept(slug, vault, leader_id):
    root, cfg = _load_vault(vault)
    if cfg.execution is None:
        raise click.ClickException("no execution config — run `cns execute init` first")
    try:
        archived = accept_review(
            reviews_root(cfg, root, leader_id=leader_id), slug, vault_root=root
        )
    except ReviewNotFoundError as e:
        raise click.ClickException(str(e)) from e
    click.echo(f"Accepted: archived to {archived}")


@reviews.command("reject")
@click.argument("slug")
@click.option("--vault", type=click.Path(path_type=Path, exists=True), default=None)
@click.option("--leader", "leader_id", default=None, help="Leader id (per-leader layout only).")
def reviews_reject(slug, vault, leader_id):
    root, cfg = _load_vault(vault)
    if cfg.execution is None:
        raise click.ClickException("no execution config — run `cns execute init` first")
    try:
        archived = reject_review(reviews_root(cfg, root, leader_id=leader_id), slug)
    except ReviewNotFoundError as e:
        raise click.ClickException(str(e)) from e
    click.echo(f"Rejected: archived to {archived}")


@cli.group()
def roles():
    """Inspect role definitions."""


@roles.command("list")
@click.option("--vault", type=click.Path(path_type=Path, exists=True), default=None)
def roles_list(vault):
    root, cfg = _load_vault(vault)
    by_parent: dict[str | None, list] = {}
    for r in cfg.roles:
        by_parent.setdefault(r.reports_to, []).append(r)

    def _print(role_id: str | None, depth: int):
        for child in sorted(by_parent.get(role_id, []), key=lambda r: r.id):
            indent = "  " * depth
            click.echo(f"{indent}- {child.name} ({child.id})  workspaces={len(child.workspaces)}")
            _print(child.id, depth + 1)

    _print(None, 0)


@cli.group()
def vault():
    """Vault-level maintenance (migrations, etc.)."""


@vault.command("migrate-reviews")
@click.option("--vault", type=click.Path(path_type=Path, exists=True), default=None)
@click.option("--apply", is_flag=True, default=False, help="Actually perform the migration.")
@click.option(
    "--undo",
    is_flag=True,
    default=False,
    help="Reverse the per-leader migration (flatten <leader>/<slug>/ back to <slug>/).",
)
@click.option(
    "--leader",
    "leader_id",
    default=None,
    help=("Leader id whose subdir to migrate to/from. Defaults to execution.top_level_leader."),
)
def vault_migrate_reviews(vault, apply, undo, leader_id):
    """Move flat Brain/Reviews/<slug>/ entries under Brain/Reviews/<leader>/<slug>/.

    Idempotent. Default mode is dry-run — pass `--apply` to mutate the disk.
    Use `--undo` to flatten a per-leader layout back to the legacy shape.

    The migration only moves bet-slug subdirs. The `.archive/` directory is
    left in place at the root (archive paths are preserved across the
    layout switch by design).
    """
    root, cfg = _load_vault(vault)
    if cfg.execution is None:
        raise click.ClickException("no execution config — run `cns execute init` first")

    leader = leader_id or cfg.execution.top_level_leader
    base = root / cfg.execution.reviews_dir
    leader_dir = base / leader

    if not base.exists():
        click.echo(f"Nothing to migrate: {base} does not exist.")
        return

    plan: list[tuple[Path, Path]] = []
    if undo:
        # Flatten <base>/<leader>/<slug>/ -> <base>/<slug>/. Skip if no
        # leader subdir (already flat — idempotent).
        if not leader_dir.exists() or not leader_dir.is_dir():
            click.echo(f"Nothing to undo: {leader_dir} does not exist.")
            return
        for child in sorted(leader_dir.iterdir()):
            if not child.is_dir() or child.name.startswith("."):
                continue
            dest = base / child.name
            if dest.exists():
                # Idempotent: dest already in place at base. Skip silently
                # rather than refuse — re-running undo on an already-undone
                # vault should be a no-op.
                continue
            plan.append((child, dest))
    else:
        # Forward migration: <base>/<slug>/ -> <base>/<leader>/<slug>/.
        leader_dir.mkdir(parents=True, exist_ok=True) if apply else None
        for child in sorted(base.iterdir()):
            if not child.is_dir():
                continue
            # Skip the .archive dir, the leader subdir itself, and any other
            # leader subdirs that may already exist.
            if child.name.startswith(".") or child.name == leader:
                continue
            # If it looks like a leader subdir (contains only bet subdirs and
            # no brief.md of its own), skip — it's another leader, not a bet.
            # Heuristic: presence of brief.md = bet review; absence + only
            # subdirs = a leader queue. Cheap check: brief.md.
            if not (child / "brief.md").exists():
                continue
            dest = leader_dir / child.name
            if dest.exists():
                continue  # idempotent
            plan.append((child, dest))

    if not plan:
        action = "undo" if undo else "migrate"
        click.echo(f"Nothing to {action}; layout is already in target shape.")
        return

    verb = "WOULD MOVE" if not apply else "Moving"
    click.echo(f"{verb} {len(plan)} review(s):")
    for src, dest in plan:
        click.echo(f"  {src.relative_to(root)}  ->  {dest.relative_to(root)}")

    if not apply:
        click.echo("\n(dry-run; pass --apply to perform the move)")
        return

    import shutil

    if not undo:
        leader_dir.mkdir(parents=True, exist_ok=True)
    for src, dest in plan:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dest))

    # If undoing and the leader subdir is now empty (no bet subdirs left),
    # remove it so a re-run can be a no-op rather than seeing a stale shell.
    if undo and leader_dir.exists():
        remaining = [p for p in leader_dir.iterdir() if not p.name.startswith(".")]
        if not remaining:
            try:
                leader_dir.rmdir()
            except OSError:
                pass

    click.echo(f"\nDone. {len(plan)} review(s) moved.")
    if not undo:
        click.echo(
            "Tip: set `execution.reviews_dir_per_leader: true` in .cns/config.yaml "
            "to make /spar and /execute use the new layout."
        )
