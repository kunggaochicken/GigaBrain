from datetime import date

from click.testing import CliRunner

from cns.bet import create_bet
from cns.cli import cli
from cns.reviews import Brief, BriefStatus, FileTouched, staged_path_for, write_brief


def test_bootstrap_creates_config_and_dirs(tmp_path):
    runner = CliRunner()
    vault = tmp_path / "v"
    vault.mkdir()
    result = runner.invoke(cli, ["bootstrap", "--vault", str(vault), "--preset", "minimal"])
    assert result.exit_code == 0, result.output
    assert (vault / ".cns/config.yaml").exists()
    assert (vault / "Brain/Bets").is_dir()
    assert (vault / "Brain/CONFLICTS.md").exists()


def test_bootstrap_refuses_overwrite(tmp_path):
    runner = CliRunner()
    vault = tmp_path / "v"
    vault.mkdir()
    runner.invoke(cli, ["bootstrap", "--vault", str(vault)])
    result = runner.invoke(cli, ["bootstrap", "--vault", str(vault)])
    assert result.exit_code != 0
    assert "already exists" in result.output


def test_validate_passes_on_sample_vault(sample_vault):
    runner = CliRunner()
    result = runner.invoke(cli, ["validate", "--vault", str(sample_vault)])
    assert result.exit_code == 0, result.output
    assert "OK" in result.output


def test_reindex_writes_bets_index(sample_vault):
    runner = CliRunner()
    result = runner.invoke(cli, ["reindex", "--vault", str(sample_vault)])
    assert result.exit_code == 0, result.output
    index_file = sample_vault / "Brain/Bets/BETS.md"
    assert index_file.exists()
    text = index_file.read_text()
    assert "## CEO" in text
    assert "[[bet_example]]" in text


def test_detect_writes_conflicts_for_unspecified_kill(sample_vault):
    runner = CliRunner()
    result = runner.invoke(cli, ["detect", "--vault", str(sample_vault), "--today", "2026-04-25"])
    assert result.exit_code == 0, result.output
    conflicts_file = sample_vault / "Brain/CONFLICTS.md"
    assert conflicts_file.exists()
    text = conflicts_file.read_text()
    assert "needs-sparring" in text or "needs sparring" in text.lower()


def test_detect_skips_malformed_bet_with_warning(sample_vault):
    bad = sample_vault / "Brain/Bets/bet_malformed.md"
    bad.write_text("---\nname: missing required fields\n---\n")
    runner = CliRunner()
    result = runner.invoke(cli, ["detect", "--vault", str(sample_vault), "--today", "2026-04-25"])
    assert result.exit_code == 0, result.output
    assert "skipping malformed bet" in result.output


def test_execute_dry_run_lists_bets(sample_vault):
    """sample_vault has one CEO-owned bet — no workspaces, so it's skipped."""
    runner = CliRunner()
    cfg_path = sample_vault / ".cns/config.yaml"
    cfg_path.write_text(
        cfg_path.read_text()
        + ("\nexecution:\n  reviews_dir: Brain/Reviews\n  top_level_leader: ceo\n")
    )
    result = runner.invoke(cli, ["execute", "--vault", str(sample_vault), "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "bet_example" in result.output
    assert "skip" in result.output.lower() or "no_workspaces" in result.output


def test_execute_init_adds_block(sample_vault):
    """`cns execute init` should add an execution{} block to a config without one."""
    runner = CliRunner()
    cfg_path = sample_vault / ".cns/config.yaml"
    assert "execution:" not in cfg_path.read_text()
    result = runner.invoke(cli, ["execute", "init", "--vault", str(sample_vault)])
    assert result.exit_code == 0, result.output
    text = cfg_path.read_text()
    assert "execution:" in text
    assert "top_level_leader: ceo" in text


def test_execute_without_init_emits_helpful_error(sample_vault):
    runner = CliRunner()
    result = runner.invoke(cli, ["execute", "--vault", str(sample_vault), "--dry-run"])
    assert result.exit_code != 0
    assert "execute init" in result.output


def test_execute_init_refuses_multi_root_config(tmp_path):
    """`cns execute init` against a flat (multi-root) config must refuse before
    writing — leaving the config file untouched and printing a helpful hint
    that names the leader and the non-leader roles to fix.
    """
    runner = CliRunner()
    vault = tmp_path / "vault"
    (vault / ".cns").mkdir(parents=True)
    (vault / "Brain/Bets").mkdir(parents=True)
    cfg_path = vault / ".cns/config.yaml"
    cfg_text = (
        "brain:\n  root: Brain\n  bets_dir: Brain/Bets\n"
        "  bets_index: Brain/Bets/BETS.md\n  conflicts_file: Brain/CONFLICTS.md\n"
        "roles:\n"
        "  - id: ceo\n    name: CEO\n"
        "  - id: cto\n    name: CTO\n"
        "  - id: cmo\n    name: CMO\n"
        "horizons:\n  this-week: 7\n  this-month: 30\n"
        "  this-quarter: 90\n  strategic: 180\n"
        "signal_sources: []\n"
    )
    cfg_path.write_text(cfg_text)
    pre_mtime = cfg_path.stat().st_mtime_ns

    result = runner.invoke(cli, ["execute", "init", "--vault", str(vault)])

    assert result.exit_code != 0
    assert "refusing to write" in result.output
    assert "multiple roots" in result.output
    # Helpful hint names the leader and the non-leader roles to fix.
    assert "reports_to: ceo" in result.output
    assert "cto" in result.output
    assert "cmo" in result.output
    # File must be unchanged byte-for-byte and untouched on disk.
    assert cfg_path.read_text() == cfg_text
    assert cfg_path.stat().st_mtime_ns == pre_mtime


def test_execute_init_succeeds_on_solo_founder_preset(tmp_path):
    """`cns bootstrap --preset solo-founder` followed by `cns execute init`
    must succeed end-to-end (regression for #19: the preset shipped flat,
    which bricked the config after init wrote `execution:`)."""
    runner = CliRunner()
    vault = tmp_path / "vault"
    vault.mkdir()
    r = runner.invoke(cli, ["bootstrap", "--vault", str(vault), "--preset", "solo-founder"])
    assert r.exit_code == 0, r.output
    r = runner.invoke(cli, ["execute", "init", "--vault", str(vault)])
    assert r.exit_code == 0, r.output
    r = runner.invoke(cli, ["validate", "--vault", str(vault)])
    assert r.exit_code == 0, r.output


def test_reviews_list_empty(sample_vault):
    """No reviews yet -> reports zero."""
    runner = CliRunner()
    cfg_path = sample_vault / ".cns/config.yaml"
    cfg_path.write_text(
        cfg_path.read_text()
        + ("\nexecution:\n  reviews_dir: Brain/Reviews\n  top_level_leader: ceo\n")
    )
    result = runner.invoke(cli, ["reviews", "list", "--vault", str(sample_vault)])
    assert result.exit_code == 0, result.output
    assert "0 pending" in result.output or "no pending" in result.output.lower()


def test_reviews_accept_promotes_and_archives(sample_vault, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "code/myapp").mkdir(parents=True)
    cfg_path = sample_vault / ".cns/config.yaml"
    cfg_path.write_text(
        cfg_path.read_text()
        + ("\nexecution:\n  reviews_dir: Brain/Reviews\n  top_level_leader: ceo\n")
    )
    review_dir = sample_vault / "Brain/Reviews/sample_slug"
    # Stage at the path accept_review will look for (HOME-expanded), since
    # `~` in the brief expands to the monkeypatched HOME.
    staged = staged_path_for("~/code/myapp/x.py", review_dir=review_dir)
    staged.parent.mkdir(parents=True)
    staged.write_text("print('x')\n")
    write_brief(
        review_dir / "brief.md",
        Brief(
            bet="bet_example.md",
            owner="ceo",
            agent_run_id="2026-04-26T00-00-00Z",
            status=BriefStatus.PENDING,
            files_touched=[FileTouched(path="~/code/myapp/x.py", action="created", bytes=10)],
        ),
    )
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "reviews",
            "accept",
            "sample_slug",
            "--vault",
            str(sample_vault),
        ],
    )
    assert result.exit_code == 0, result.output
    assert (tmp_path / "code/myapp/x.py").read_text() == "print('x')\n"
    assert not review_dir.exists()


def test_reviews_accept_uses_vault_root_for_relative_paths(sample_vault, tmp_path):
    """When reviews_dir is non-default, vault-relative file paths in the brief
    must still anchor against the vault root, not reviews_dir.parent.parent."""
    cfg_path = sample_vault / ".cns/config.yaml"
    cfg_path.write_text(
        cfg_path.read_text()
        + ("\nexecution:\n  reviews_dir: custom/somewhere/Reviews\n  top_level_leader: ceo\n")
    )
    review_dir = sample_vault / "custom/somewhere/Reviews/x"
    real_staged = staged_path_for("Brain/Marketing/post.md", review_dir=review_dir)
    real_staged.parent.mkdir(parents=True, exist_ok=True)
    real_staged.write_text("draft\n")
    write_brief(
        review_dir / "brief.md",
        Brief(
            bet="bet_example.md",
            owner="ceo",
            agent_run_id="2026-04-26T00-00-00Z",
            status=BriefStatus.PENDING,
            files_touched=[FileTouched(path="Brain/Marketing/post.md", action="created", bytes=6)],
        ),
    )
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "reviews",
            "accept",
            "x",
            "--vault",
            str(sample_vault),
        ],
    )
    assert result.exit_code == 0, result.output
    promoted = sample_vault / "Brain/Marketing/post.md"
    assert promoted.exists()
    assert promoted.read_text() == "draft\n"


def test_roles_list_prints_tree(sample_vault):
    cfg_path = sample_vault / ".cns/config.yaml"
    cfg_path.write_text(
        "brain:\n  root: Brain\n  bets_dir: Brain/Bets\n"
        "  bets_index: Brain/Bets/BETS.md\n  conflicts_file: Brain/CONFLICTS.md\n"
        "roles:\n"
        "  - id: ceo\n    name: CEO\n    reports_to: null\n"
        "  - id: cto\n    name: CTO\n    reports_to: ceo\n"
        "horizons:\n  this-week: 7\n  this-month: 30\n"
        "  this-quarter: 90\n  strategic: 180\n"
        "signal_sources: []\n"
    )
    runner = CliRunner()
    result = runner.invoke(cli, ["roles", "list", "--vault", str(sample_vault)])
    assert result.exit_code == 0, result.output
    assert "CEO" in result.output
    assert "CTO" in result.output
    lines = result.output.splitlines()
    cto_idx = next(i for i, line in enumerate(lines) if "CTO" in line)
    assert lines[cto_idx].startswith(" ") or lines[cto_idx].startswith("\t")


def _exec_block(per_leader: bool = False) -> str:
    leaf = "  reviews_dir_per_leader: true\n" if per_leader else ""
    return "\nexecution:\n  reviews_dir: Brain/Reviews\n  top_level_leader: ceo\n" + leaf


def test_reviews_list_routes_to_per_leader_subdir(sample_vault):
    """Flag-on: `cns reviews list` reads <reviews_dir>/<leader>/, not the flat root."""
    cfg_path = sample_vault / ".cns/config.yaml"
    cfg_path.write_text(cfg_path.read_text() + _exec_block(per_leader=True))
    # Drop a brief at the per-leader path; the flat path should NOT be hit.
    leader_review = sample_vault / "Brain/Reviews/ceo/strategic_check"
    write_brief(
        leader_review / "brief.md",
        Brief(
            bet="bet_strategic_check.md",
            owner="ceo",
            agent_run_id="2026-04-26T10-00-00Z",
            status=BriefStatus.PENDING,
        ),
    )
    # And one in the legacy flat location that must NOT show up.
    write_brief(
        sample_vault / "Brain/Reviews/legacy_should_not_appear/brief.md",
        Brief(
            bet="bet_legacy.md",
            owner="ceo",
            agent_run_id="2026-04-26T09-00-00Z",
            status=BriefStatus.PENDING,
        ),
    )
    runner = CliRunner()
    r = runner.invoke(cli, ["reviews", "list", "--vault", str(sample_vault)])
    assert r.exit_code == 0, r.output
    assert "strategic_check" in r.output
    assert "legacy_should_not_appear" not in r.output


def test_reviews_list_legacy_layout_unchanged(sample_vault):
    """Flag-off: behavior matches the v1 default (briefs land at the flat root)."""
    cfg_path = sample_vault / ".cns/config.yaml"
    cfg_path.write_text(cfg_path.read_text() + _exec_block(per_leader=False))
    write_brief(
        sample_vault / "Brain/Reviews/flat_brief/brief.md",
        Brief(
            bet="bet_flat.md",
            owner="ceo",
            agent_run_id="2026-04-26T09-00-00Z",
            status=BriefStatus.PENDING,
        ),
    )
    runner = CliRunner()
    r = runner.invoke(cli, ["reviews", "list", "--vault", str(sample_vault)])
    assert r.exit_code == 0, r.output
    assert "flat_brief" in r.output


def test_vault_migrate_reviews_dry_run_default(sample_vault):
    """No --apply -> nothing moves; output enumerates the plan."""
    cfg_path = sample_vault / ".cns/config.yaml"
    cfg_path.write_text(cfg_path.read_text() + _exec_block(per_leader=False))
    review = sample_vault / "Brain/Reviews/foo"
    write_brief(
        review / "brief.md",
        Brief(
            bet="bet_foo.md",
            owner="ceo",
            agent_run_id="2026-04-26T00-00-00Z",
            status=BriefStatus.PENDING,
        ),
    )
    runner = CliRunner()
    r = runner.invoke(cli, ["vault", "migrate-reviews", "--vault", str(sample_vault)])
    assert r.exit_code == 0, r.output
    assert "WOULD MOVE" in r.output
    assert "Brain/Reviews/foo" in r.output
    assert review.exists()  # untouched
    assert not (sample_vault / "Brain/Reviews/ceo/foo").exists()


def test_vault_migrate_reviews_apply_then_idempotent(sample_vault):
    """Forward migration moves <slug>/ -> <leader>/<slug>/. Re-run is a no-op."""
    cfg_path = sample_vault / ".cns/config.yaml"
    cfg_path.write_text(cfg_path.read_text() + _exec_block(per_leader=False))
    review = sample_vault / "Brain/Reviews/foo"
    write_brief(
        review / "brief.md",
        Brief(
            bet="bet_foo.md",
            owner="ceo",
            agent_run_id="2026-04-26T00-00-00Z",
            status=BriefStatus.PENDING,
        ),
    )
    runner = CliRunner()
    r = runner.invoke(cli, ["vault", "migrate-reviews", "--apply", "--vault", str(sample_vault)])
    assert r.exit_code == 0, r.output
    assert (sample_vault / "Brain/Reviews/ceo/foo/brief.md").exists()
    assert not review.exists()

    # Idempotent: a second --apply on the migrated vault is a no-op.
    r2 = runner.invoke(cli, ["vault", "migrate-reviews", "--apply", "--vault", str(sample_vault)])
    assert r2.exit_code == 0, r2.output
    assert "Nothing to migrate" in r2.output


def test_vault_migrate_reviews_undo_reverses(sample_vault):
    """--undo flattens <leader>/<slug>/ back to <slug>/. Idempotent on a flat vault."""
    cfg_path = sample_vault / ".cns/config.yaml"
    cfg_path.write_text(cfg_path.read_text() + _exec_block(per_leader=False))
    # Start in per-leader shape directly (simulates a vault that flipped the
    # flag and now wants to roll back).
    write_brief(
        sample_vault / "Brain/Reviews/ceo/foo/brief.md",
        Brief(
            bet="bet_foo.md",
            owner="ceo",
            agent_run_id="2026-04-26T00-00-00Z",
            status=BriefStatus.PENDING,
        ),
    )
    runner = CliRunner()
    r = runner.invoke(
        cli, ["vault", "migrate-reviews", "--undo", "--apply", "--vault", str(sample_vault)]
    )
    assert r.exit_code == 0, r.output
    assert (sample_vault / "Brain/Reviews/foo/brief.md").exists()
    assert not (sample_vault / "Brain/Reviews/ceo").exists()

    # Re-running --undo on the now-flat vault is a no-op.
    r2 = runner.invoke(
        cli, ["vault", "migrate-reviews", "--undo", "--apply", "--vault", str(sample_vault)]
    )
    assert r2.exit_code == 0, r2.output
    assert "Nothing to undo" in r2.output


def test_vault_migrate_reviews_preserves_archive(sample_vault):
    """The .archive/ directory must stay at the reviews root across migrations."""
    cfg_path = sample_vault / ".cns/config.yaml"
    cfg_path.write_text(cfg_path.read_text() + _exec_block(per_leader=False))
    archive = sample_vault / "Brain/Reviews/.archive/2026-04-25T00-00-00Z_old"
    archive.mkdir(parents=True)
    (archive / "brief.md").write_text("---\nx: 1\n---\n")
    write_brief(
        sample_vault / "Brain/Reviews/foo/brief.md",
        Brief(
            bet="bet_foo.md",
            owner="ceo",
            agent_run_id="2026-04-26T00-00-00Z",
            status=BriefStatus.PENDING,
        ),
    )
    runner = CliRunner()
    r = runner.invoke(cli, ["vault", "migrate-reviews", "--apply", "--vault", str(sample_vault)])
    assert r.exit_code == 0, r.output
    # Archive at the reviews root, untouched.
    assert (sample_vault / "Brain/Reviews/.archive/2026-04-25T00-00-00Z_old/brief.md").exists()
    # Bet review moved under the leader.
    assert (sample_vault / "Brain/Reviews/ceo/foo/brief.md").exists()


def test_end_to_end_create_init_dispatch_accept(tmp_path, monkeypatch):
    """Full loop: bootstrap a vault, init execution, write a CTO-owned bet,
    plan a dispatch, simulate a brief landing, accept it."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home/code/myapp").mkdir(parents=True)
    runner = CliRunner()
    vault = tmp_path / "vault"
    vault.mkdir()

    r = runner.invoke(cli, ["bootstrap", "--vault", str(vault)])
    assert r.exit_code == 0, r.output

    cfg_path = vault / ".cns/config.yaml"
    cfg_path.write_text(
        "schema_version: 2\n"
        "brain:\n  root: Brain\n  bets_dir: Brain/Bets\n"
        "  bets_index: Brain/Bets/BETS.md\n  conflicts_file: Brain/CONFLICTS.md\n"
        "roles:\n"
        "  - id: ceo\n    name: CEO\n    reports_to: null\n"
        "  - id: cto\n    name: CTO\n    reports_to: ceo\n"
        "    workspaces:\n      - path: ~/code/myapp\n        mode: read-write\n"
        "    tools:\n      bash_allowlist: [pytest]\n      web: false\n"
        "    persona: |\n      You are the CTO.\n"
        "horizons:\n  this-week: 7\n  this-month: 30\n"
        "  this-quarter: 90\n  strategic: 180\n"
        "signal_sources: []\n"
        "execution:\n  reviews_dir: Brain/Reviews\n  top_level_leader: ceo\n"
    )

    create_bet(
        bets_dir=vault / "Brain/Bets",
        name="Refactor auth module",
        description="Move JWT logic out of the request handler.",
        owner="cto",
        horizon="this-week",
        confidence="medium",
        kill_criteria="A simpler approach surfaces in code review.",
        body_the_bet="Extract jwt_handler.py from request_handler.py.",
        today=date(2026, 4, 26),
    )

    # Plan dispatch (dry-run)
    r = runner.invoke(cli, ["execute", "--vault", str(vault), "--dry-run"])
    assert r.exit_code == 0, r.output
    assert "DISPATCH" in r.output
    assert "refactor_auth_module" in r.output

    # Real run writes the hook config
    r = runner.invoke(cli, ["execute", "--vault", str(vault)])
    assert r.exit_code == 0, r.output
    assert (vault / ".cns/.agent-hooks/refactor_auth_module.json").exists()
    assert (vault / "Brain/Reviews/refactor_auth_module").is_dir()

    # Simulate the agent producing a brief and a staged file.
    review_dir = vault / "Brain/Reviews/refactor_auth_module"
    staged = staged_path_for("~/code/myapp/jwt_handler.py", review_dir=review_dir)
    staged.parent.mkdir(parents=True, exist_ok=True)
    staged.write_text("# jwt_handler\n")
    write_brief(
        review_dir / "brief.md",
        Brief(
            bet="bet_refactor_auth_module.md",
            owner="cto",
            agent_run_id="2026-04-26T15-00-00Z",
            status=BriefStatus.PENDING,
            proposed_closure=True,
            files_touched=[
                FileTouched(
                    path="~/code/myapp/jwt_handler.py",
                    action="created",
                    bytes=14,
                )
            ],
            body_tldr="Extracted jwt_handler.py.",
            body_decisions_needed="None — proceed to accept or reject.",
        ),
    )

    # Reviews list shows it
    r = runner.invoke(cli, ["reviews", "list", "--vault", str(vault)])
    assert r.exit_code == 0, r.output
    assert "refactor_auth_module" in r.output

    # Accept promotes the file into the workspace
    r = runner.invoke(cli, ["reviews", "accept", "refactor_auth_module", "--vault", str(vault)])
    assert r.exit_code == 0, r.output
    promoted = tmp_path / "home/code/myapp/jwt_handler.py"
    assert promoted.exists(), f"file not promoted; output={r.output}"
    assert promoted.read_text() == "# jwt_handler\n"
    assert not review_dir.exists()
    archive_dir = vault / "Brain/Reviews/.archive"
    assert archive_dir.exists()
    archived = list(archive_dir.iterdir())
    msg = f"review not archived under {archive_dir}; saw: {archived}"
    assert any("refactor_auth_module" in p.name for p in archived), msg


# ---------------------------------------------------------------------------
# Issue #12: cost-controls CLI surfaces.
# ---------------------------------------------------------------------------


def test_execute_estimate_prints_per_bet_and_session_total(tmp_path, monkeypatch):
    """--estimate prints '[role] estimated $X.YY' and a session total without dispatching."""
    runner = CliRunner()
    vault = tmp_path / "vault"
    vault.mkdir()

    r = runner.invoke(cli, ["bootstrap", "--vault", str(vault)])
    assert r.exit_code == 0, r.output

    cfg_path = vault / ".cns/config.yaml"
    cfg_path.write_text(
        "schema_version: 2\n"
        "brain:\n  root: Brain\n  bets_dir: Brain/Bets\n"
        "  bets_index: Brain/Bets/BETS.md\n  conflicts_file: Brain/CONFLICTS.md\n"
        "roles:\n"
        "  - id: ceo\n    name: CEO\n    reports_to: null\n"
        "  - id: cto\n    name: CTO\n    reports_to: ceo\n"
        "    workspaces:\n      - path: ~/code/myapp\n        mode: read-write\n"
        "horizons:\n  this-week: 7\n  this-month: 30\n"
        "  this-quarter: 90\n  strategic: 180\n"
        "signal_sources: []\n"
        "execution:\n  reviews_dir: Brain/Reviews\n  top_level_leader: ceo\n"
    )
    create_bet(
        bets_dir=vault / "Brain/Bets",
        name="Refactor auth module",
        description="Move JWT logic out.",
        owner="cto",
        horizon="this-week",
        confidence="medium",
        kill_criteria="A simpler approach surfaces.",
        body_the_bet="Extract jwt_handler.py.",
        today=date(2026, 4, 26),
    )
    r = runner.invoke(cli, ["execute", "--vault", str(vault), "--estimate"])
    assert r.exit_code == 0, r.output
    assert "estimated $" in r.output
    assert "[cto]" in r.output
    assert "Session total" in r.output
    # The dispatch path must NOT have run.
    assert not (vault / ".cns/.agent-hooks/refactor_auth_module.json").exists()


def test_execute_refuses_per_run_breach(tmp_path):
    """A bet whose estimate exceeds per_run_usd_max is refused with a clear error
    and is NOT dispatched (no hook config written)."""
    runner = CliRunner()
    vault = tmp_path / "vault"
    vault.mkdir()
    runner.invoke(cli, ["bootstrap", "--vault", str(vault)])
    cfg_path = vault / ".cns/config.yaml"
    cfg_path.write_text(
        "schema_version: 2\n"
        "brain:\n  root: Brain\n  bets_dir: Brain/Bets\n"
        "  bets_index: Brain/Bets/BETS.md\n  conflicts_file: Brain/CONFLICTS.md\n"
        "roles:\n"
        "  - id: ceo\n    name: CEO\n    reports_to: null\n"
        "  - id: cto\n    name: CTO\n    reports_to: ceo\n"
        "    workspaces:\n      - path: ~/code/myapp\n        mode: read-write\n"
        "horizons:\n  this-week: 7\n  this-month: 30\n"
        "  this-quarter: 90\n  strategic: 180\n"
        "signal_sources: []\n"
        "execution:\n  reviews_dir: Brain/Reviews\n  top_level_leader: ceo\n"
        "  budgets:\n    per_run_usd_max: '0.001'\n"
    )
    create_bet(
        bets_dir=vault / "Brain/Bets",
        name="Refactor auth module",
        description="Move JWT logic out.",
        owner="cto",
        horizon="this-week",
        confidence="medium",
        kill_criteria="A simpler approach surfaces.",
        body_the_bet="Extract jwt_handler.py.",
        today=date(2026, 4, 26),
    )
    r = runner.invoke(cli, ["execute", "--vault", str(vault), "--dry-run"])
    assert r.exit_code == 0, r.output
    assert "budget_per_run" in r.output
    assert "per_run_usd_max breach" in r.output
    assert "refactor_auth_module" in r.output


def test_reports_cost_summarizes_by_role(tmp_path):
    """`cns reports cost --since` walks the archive and prints a per-role table."""
    from decimal import Decimal

    from cns.reviews import Brief, BriefStatus, CostRecord, write_brief

    runner = CliRunner()
    vault = tmp_path / "vault"
    vault.mkdir()
    runner.invoke(cli, ["bootstrap", "--vault", str(vault)])
    cfg_path = vault / ".cns/config.yaml"
    cfg_path.write_text(
        cfg_path.read_text()
        + ("\nexecution:\n  reviews_dir: Brain/Reviews\n  top_level_leader: ceo\n")
    )

    reviews_dir = vault / "Brain/Reviews"
    for slug, owner, usd, run_id in [
        ("a", "cto", "0.40", "2026-04-25T10-00-00Z"),
        ("b", "cto", "0.30", "2026-04-25T11-00-00Z"),
        ("c", "cmo", "0.10", "2026-04-25T12-00-00Z"),
    ]:
        d = reviews_dir / ".archive" / slug
        d.mkdir(parents=True, exist_ok=True)
        write_brief(
            d / "brief.md",
            Brief(
                bet=f"bet_{slug}.md",
                owner=owner,
                agent_run_id=run_id,
                status=BriefStatus.ACCEPTED,
                cost=CostRecord(
                    model="claude-opus-4-7",
                    input_tokens=1000,
                    output_tokens=2000,
                    usd=Decimal(usd),
                ),
            ),
        )

    r = runner.invoke(
        cli,
        [
            "reports",
            "cost",
            "--vault",
            str(vault),
            "--since",
            "2026-04-25",
            "--until",
            "2026-04-25",
            "--by",
            "role",
        ],
    )
    assert r.exit_code == 0, r.output
    assert "cto" in r.output
    assert "cmo" in r.output
    assert "$0.70" in r.output  # cto total
    assert "$0.10" in r.output  # cmo total
    assert "TOTAL" in r.output


def test_reports_cost_filters_outside_window(tmp_path):
    """Briefs outside [since, until] must NOT contribute."""
    from decimal import Decimal

    from cns.reviews import Brief, BriefStatus, CostRecord, write_brief

    runner = CliRunner()
    vault = tmp_path / "vault"
    vault.mkdir()
    runner.invoke(cli, ["bootstrap", "--vault", str(vault)])
    cfg_path = vault / ".cns/config.yaml"
    cfg_path.write_text(
        cfg_path.read_text()
        + ("\nexecution:\n  reviews_dir: Brain/Reviews\n  top_level_leader: ceo\n")
    )

    reviews_dir = vault / "Brain/Reviews"
    d = reviews_dir / ".archive" / "old"
    d.mkdir(parents=True, exist_ok=True)
    write_brief(
        d / "brief.md",
        Brief(
            bet="bet_old.md",
            owner="ceo",
            agent_run_id="2025-12-01T10-00-00Z",
            status=BriefStatus.ACCEPTED,
            cost=CostRecord(
                model="claude-opus-4-7",
                input_tokens=1,
                output_tokens=1,
                usd=Decimal("99.99"),
            ),
        ),
    )

    r = runner.invoke(
        cli,
        [
            "reports",
            "cost",
            "--vault",
            str(vault),
            "--since",
            "2026-04-01",
        ],
    )
    assert r.exit_code == 0, r.output
    assert "No costed briefs" in r.output


def test_reviews_list_includes_cost_tag(tmp_path):
    """`cns reviews list` prefixes each row with `[$X.YY]` when the brief
    has a cost block — the `/spar` Phase 2 walk shows the same format."""
    from decimal import Decimal

    from cns.reviews import Brief, BriefStatus, CostRecord, write_brief

    runner = CliRunner()
    vault = tmp_path / "vault"
    vault.mkdir()
    runner.invoke(cli, ["bootstrap", "--vault", str(vault)])
    cfg_path = vault / ".cns/config.yaml"
    cfg_path.write_text(
        cfg_path.read_text()
        + ("\nexecution:\n  reviews_dir: Brain/Reviews\n  top_level_leader: ceo\n")
    )

    review_dir = vault / "Brain/Reviews/sample_slug"
    write_brief(
        review_dir / "brief.md",
        Brief(
            bet="bet_sample_slug.md",
            owner="ceo",
            agent_run_id="2026-04-26T00-00-00Z",
            status=BriefStatus.PENDING,
            cost=CostRecord(
                model="claude-opus-4-7",
                input_tokens=1000,
                output_tokens=2000,
                usd=Decimal("0.4523"),
            ),
        ),
    )
    r = runner.invoke(cli, ["reviews", "list", "--vault", str(vault)])
    assert r.exit_code == 0, r.output
    # The exact format the `/spar` skill is documented to expect.
    assert "[$0.45]" in r.output
    assert "sample_slug" in r.output


# ---------------------------------------------------------------------------
# Issue #9: recursive sub-delegation CLI.
# ---------------------------------------------------------------------------


def _three_level_vault(tmp_path):
    """Bootstrap a vault wired with a CEO -> CTO -> engineer org tree.

    Returns (vault_root, runner).
    """
    runner = CliRunner()
    vault = tmp_path / "vault"
    vault.mkdir()
    runner.invoke(cli, ["bootstrap", "--vault", str(vault)])
    cfg_path = vault / ".cns/config.yaml"
    cfg_path.write_text(
        "schema_version: 2\n"
        "brain:\n  root: Brain\n  bets_dir: Brain/Bets\n"
        "  bets_index: Brain/Bets/BETS.md\n  conflicts_file: Brain/CONFLICTS.md\n"
        "roles:\n"
        "  - id: ceo\n    name: CEO\n    reports_to: null\n"
        "  - id: cto\n    name: CTO\n    reports_to: ceo\n"
        "    workspaces:\n      - path: ~/code/myapp\n        mode: read-write\n"
        "  - id: engineer\n    name: Engineer\n    reports_to: cto\n"
        "    workspaces:\n      - path: ~/code/myapp/engine\n        mode: read-write\n"
        "  - id: cmo\n    name: CMO\n    reports_to: ceo\n"
        "    workspaces:\n      - path: Brain/Marketing\n        mode: read-write\n"
        "horizons:\n  this-week: 7\n  this-month: 30\n"
        "  this-quarter: 90\n  strategic: 180\n"
        "signal_sources: []\n"
        "execution:\n  reviews_dir: Brain/Reviews\n  top_level_leader: ceo\n"
    )
    return vault, runner


def test_cli_execute_from_leader_happy_path(tmp_path):
    """`cns execute --from-leader cto --bet engineer_thing` dispatches an
    engineer sub-agent and prints `[depth=N] [DISPATCH]` plus the per-leader
    review_dir routing."""
    vault, runner = _three_level_vault(tmp_path)
    create_bet(
        bets_dir=vault / "Brain/Bets",
        name="Fix JWT bug",
        description="A subtle issue in the engine.",
        owner="engineer",
        horizon="this-week",
        confidence="medium",
        kill_criteria="Bug turns out to be unrelated.",
        body_the_bet="Patch jwt_handler.py.",
        today=date(2026, 4, 26),
    )
    r = runner.invoke(
        cli,
        [
            "execute",
            "--vault",
            str(vault),
            "--from-leader",
            "cto",
            "--bet",
            "fix_jwt_bug",
        ],
    )
    assert r.exit_code == 0, r.output
    assert "[DISPATCH]" in r.output
    assert "depth=2" in r.output
    assert "fix_jwt_bug" in r.output
    # Routing: review_dir lands under cto/.
    assert "Brain/Reviews/cto/fix_jwt_bug" in r.output


def test_cli_execute_from_leader_refuses_non_subordinate(tmp_path):
    """The CTO trying to dispatch a CMO-owned bet exits non-zero with
    ROLE_NOT_SUBORDINATE on stderr."""
    vault, runner = _three_level_vault(tmp_path)
    create_bet(
        bets_dir=vault / "Brain/Bets",
        name="Press outreach",
        description="x",
        owner="cmo",
        horizon="this-week",
        confidence="low",
        kill_criteria="x",
        body_the_bet="x",
        today=date(2026, 4, 26),
    )
    r = runner.invoke(
        cli,
        [
            "execute",
            "--vault",
            str(vault),
            "--from-leader",
            "cto",
            "--bet",
            "press_outreach",
        ],
    )
    assert r.exit_code != 0
    assert "role_not_subordinate" in r.output


def test_cli_execute_from_leader_refuses_cycle(tmp_path):
    """A chain that already includes the sub-bet's owner exits non-zero
    with cycle_detected on stderr."""
    vault, runner = _three_level_vault(tmp_path)
    # Bump the depth cap so this test isolates the cycle path; without it
    # a synthetic chain of length 4 trips depth_limit first.
    cfg_path = vault / ".cns/config.yaml"
    cfg_path.write_text(
        cfg_path.read_text().replace(
            "  top_level_leader: ceo\n",
            "  top_level_leader: ceo\n  max_dispatch_depth: 10\n",
        )
    )
    create_bet(
        bets_dir=vault / "Brain/Bets",
        name="Fix JWT bug",
        description="x",
        owner="engineer",
        horizon="this-week",
        confidence="low",
        kill_criteria="x",
        body_the_bet="x",
        today=date(2026, 4, 26),
    )
    chain_json = '[["ceo","vision"],["cto","refactor"],["engineer","first_pass"],["cto","retry"]]'
    r = runner.invoke(
        cli,
        [
            "execute",
            "--vault",
            str(vault),
            "--from-leader",
            "cto",
            "--bet",
            "fix_jwt_bug",
            "--chain",
            chain_json,
        ],
    )
    assert r.exit_code != 0
    assert "cycle_detected" in r.output


def test_cli_execute_from_leader_refuses_depth(tmp_path):
    """When the depth cap is hit, the CLI exits non-zero with depth_limit."""
    vault, runner = _three_level_vault(tmp_path)
    # Lower the cap so the engineer's hop trips it. Patch in max_dispatch_depth.
    cfg_path = vault / ".cns/config.yaml"
    cfg_path.write_text(
        cfg_path.read_text().replace(
            "  top_level_leader: ceo\n",
            "  top_level_leader: ceo\n  max_dispatch_depth: 2\n",
        )
    )
    create_bet(
        bets_dir=vault / "Brain/Bets",
        name="Fix JWT bug",
        description="x",
        owner="engineer",
        horizon="this-week",
        confidence="low",
        kill_criteria="x",
        body_the_bet="x",
        today=date(2026, 4, 26),
    )
    chain_json = '[["ceo","vision"],["cto","refactor"]]'  # already length 2
    r = runner.invoke(
        cli,
        [
            "execute",
            "--vault",
            str(vault),
            "--from-leader",
            "cto",
            "--bet",
            "fix_jwt_bug",
            "--chain",
            chain_json,
        ],
    )
    assert r.exit_code != 0
    assert "depth_limit" in r.output


def test_cli_execute_from_leader_requires_bet(tmp_path):
    """Missing --bet under --from-leader is a hard error."""
    vault, runner = _three_level_vault(tmp_path)
    r = runner.invoke(
        cli,
        ["execute", "--vault", str(vault), "--from-leader", "cto"],
    )
    assert r.exit_code != 0
    assert "--bet" in r.output


def test_cli_execute_from_leader_dry_run_writes_nothing(tmp_path):
    """--dry-run on a sub-dispatch leaves no envelope artifacts behind."""
    vault, runner = _three_level_vault(tmp_path)
    create_bet(
        bets_dir=vault / "Brain/Bets",
        name="Fix JWT bug",
        description="x",
        owner="engineer",
        horizon="this-week",
        confidence="low",
        kill_criteria="x",
        body_the_bet="x",
        today=date(2026, 4, 26),
    )
    r = runner.invoke(
        cli,
        [
            "execute",
            "--vault",
            str(vault),
            "--from-leader",
            "cto",
            "--bet",
            "fix_jwt_bug",
            "--dry-run",
        ],
    )
    assert r.exit_code == 0, r.output
    assert "[DISPATCH]" in r.output
    assert "(dry-run" in r.output
    # The hook config and review subdir must be cleaned up.
    assert not (vault / ".cns/.agent-hooks/fix_jwt_bug.json").exists()
    assert not (vault / "Brain/Reviews/cto/fix_jwt_bug").exists()
