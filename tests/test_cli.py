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
