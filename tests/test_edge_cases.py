"""Edge cases and regressions for engine, memory, checkpoint, config, adapters, CLI."""
import os

import pytest

from agent_handover.adapters import _agents_md
from agent_handover.adapters.cline import install_clinerules
from agent_handover.adapters.codex import install_agents_md
from agent_handover.checkpoint import (
    RESUME_COMPLETED,
    RESUME_NEEDED,
    RESUME_NONE,
    Checkpoint,
)
from agent_handover.cli import main
from agent_handover.backends import publish_or_raise
from agent_handover.config import _build_backend, build_engine_from_config
from agent_handover.engine import HandoverEngine, PauseError, Step, StepError
from agent_handover.memory import MemoryStore


def recorder(log, *names):
    return [Step(n, lambda n=n: log.append(n)) for n in names]


# -- engine --------------------------------------------------------------
def test_engine_runs_steps_unknown_to_interrupted_checkpoint(tmp_path):
    # regression: steps added since the interrupted run were silently skipped
    cp = Checkpoint(tmp_path / "cp.json")
    cp.start(["old"])
    log = []
    engine = HandoverEngine(recorder(log, "a", "b"), cp)
    assert engine.run() == ["a", "b"]
    assert log == ["a", "b"]


def test_engine_resume_skips_done_and_runs_new(tmp_path):
    cp = Checkpoint(tmp_path / "cp.json")
    cp.start(["a", "b"])
    cp.mark_done("a")
    log = []
    assert HandoverEngine(recorder(log, "a", "b", "c"), cp).run() == ["b", "c"]


def test_engine_resume_false_reruns_everything(tmp_path):
    cp = Checkpoint(tmp_path / "cp.json")
    cp.start(["a", "b"])
    cp.mark_done("a")
    log = []
    assert HandoverEngine(recorder(log, "a", "b"), cp).run(resume=False) == ["a", "b"]


def test_engine_after_completed_run_starts_fresh(tmp_path):
    cp = Checkpoint(tmp_path / "cp.json")
    log = []
    engine = HandoverEngine(recorder(log, "a"), cp)
    engine.run()
    assert engine.run() == ["a"]
    assert log == ["a", "a"]


def test_engine_empty_steps_completes(tmp_path):
    cp = Checkpoint(tmp_path / "cp.json")
    assert HandoverEngine([], cp).run() == []
    assert cp.resume_code() == RESUME_COMPLETED


def test_engine_pause_between_steps(tmp_path):
    pause = tmp_path / "PAUSE"
    cp = Checkpoint(tmp_path / "cp.json")
    steps = [Step("a", lambda: pause.write_text("")), Step("b", lambda: None)]
    with pytest.raises(PauseError):
        HandoverEngine(steps, cp, pause_file=pause).run()
    assert cp.pending_steps() == ["b"]
    assert cp.resume_code() == RESUME_NEEDED


def test_step_error_carries_cause(tmp_path):
    err = ValueError("bad")

    def fail():
        raise err
    with pytest.raises(StepError) as exc:
        HandoverEngine([Step("x", fail)], Checkpoint(tmp_path / "cp.json")).run()
    assert exc.value.step_name == "x"
    assert exc.value.cause is err
    assert "step 'x' failed: bad" in str(exc.value)


# -- checkpoint ----------------------------------------------------------
def test_checkpoint_load_default(tmp_path):
    data = Checkpoint(tmp_path / "none.json").load()
    assert data == {"status": "none", "steps": {}, "started_at": None, "finished_at": None}


def test_checkpoint_save_creates_parent_and_no_tmp_left(tmp_path):
    cp = Checkpoint(tmp_path / "deep" / "dir" / "cp.json")
    cp.start(["a"])
    assert cp.path.exists()
    assert not cp.path.with_suffix(".tmp").exists()


def test_checkpoint_in_progress_all_done_reports_completed(tmp_path):
    cp = Checkpoint(tmp_path / "cp.json")
    cp.start(["a"])
    cp.mark_done("a")
    assert cp.resume_code() == RESUME_COMPLETED


def test_checkpoint_unknown_status_is_none(tmp_path):
    cp = Checkpoint(tmp_path / "cp.json")
    cp._save({"status": "weird", "steps": {}, "started_at": None, "finished_at": None})
    assert cp.resume_code() == RESUME_NONE


def test_checkpoint_complete_sets_finished_at(tmp_path):
    cp = Checkpoint(tmp_path / "cp.json")
    cp.start(["a"])
    cp.complete()
    assert cp.load()["finished_at"] is not None


# -- memory --------------------------------------------------------------
def test_write_rejects_invalid_layer(tmp_path):
    with pytest.raises(ValueError):
        MemoryStore(tmp_path).write(4, "x")


def test_write_dry_run_returns_path_without_writing(tmp_path):
    p = MemoryStore(tmp_path).write(1, "x", tag="t", date_str="2026-01-02", dry_run=True)
    assert p == tmp_path / "layer1" / "2026-01" / "t-2026-01-02.md"
    assert not p.exists()


def test_write_sanitizes_tag(tmp_path):
    p = MemoryStore(tmp_path).write(1, "x", tag="a/b c", date_str="2026-01-02")
    assert p.name == "a-b_c-2026-01-02.md"


def test_read_latest_tag_with_space_round_trips(tmp_path):
    # regression: write() sanitized the tag but read_latest() did not
    store = MemoryStore(tmp_path)
    store.write(1, "note", tag="my tag", date_str="2026-06-01")
    assert store.read_latest(1, tag="my tag").endswith("note")


def test_read_latest_tag_is_not_substring_match(tmp_path):
    # regression: tag "codex" returned the newer "codex-cli" note
    store = MemoryStore(tmp_path)
    old = store.write(1, "codex note", tag="codex", date_str="2026-06-01")
    store.write(1, "cli note", tag="codex-cli", date_str="2026-06-02")
    os.utime(old, (1, 1))
    assert store.read_latest(1, tag="codex").endswith("codex note")
    assert store.read_latest(1, tag="dex") == ""


def test_read_latest_layer3_by_tag(tmp_path):
    store = MemoryStore(tmp_path)
    store.write(3, "projx archive", tag="projx", date_str="2026-05-31")
    store.write(3, "other archive", tag="other", date_str="2026-05-31")
    assert store.read_latest(3, tag="projx").endswith("projx archive")
    assert store.read_latest(3, tag="proj") == ""


def test_layer1_note_count_missing_dir(tmp_path):
    assert MemoryStore(tmp_path).layer1_note_count() == 0
    assert MemoryStore(tmp_path).layer1_note_count("2026-01") == 0


# -- config --------------------------------------------------------------
def test_config_paths_string_is_wrapped(tmp_path):
    # regression: paths = "memory" became ["m", "e", "m", ...]
    assert _build_backend({"paths": "memory"}, "memory", False).paths == ["memory"]


def test_config_unknown_backend_raises():
    with pytest.raises(ValueError, match="unknown backend type"):
        _build_backend({"type": "s3"}, "memory", None)


def test_config_missing_note_raises():
    with pytest.raises(ValueError, match="no session note"):
        build_engine_from_config({"backend": {"type": "null"}})


def test_publish_or_raise_raises_on_false():
    class _B:
        def __init__(self, ok):
            self.ok = ok

        def publish(self, message, dry_run=False):
            return self.ok

    publish_or_raise(_B(True), "m")
    with pytest.raises(RuntimeError, match="publish failed"):
        publish_or_raise(_B(False), "m")


def test_config_publish_failure_keeps_step_pending(tmp_path):
    cp = tmp_path / "cp.json"
    cfg = {
        "handover": {"memory_dir": str(tmp_path / "memory")},
        "backend": {"type": "git", "repo_dir": str(tmp_path / "not-a-repo"), "push": False},
    }
    engine = build_engine_from_config(cfg, note="n", checkpoint=cp)
    with pytest.raises(StepError):
        engine.run()
    assert Checkpoint(cp).pending_steps() == ["publish"]


# -- adapters ------------------------------------------------------------
ORPHAN = "intro\n<!-- agent-handover:begin -->\nhuman notes keep me\n"


def test_agents_md_orphan_begin_marker_keeps_human_text(tmp_path):
    # regression: a stray BEGIN marker made re-install delete text after it
    path = tmp_path / "AGENTS.md"
    path.write_text(ORPHAN, encoding="utf-8")
    assert install_agents_md(path, checkpoint="a.json") is True
    assert install_agents_md(path, checkpoint="b.json") is True
    text = path.read_text(encoding="utf-8")
    assert "human notes keep me" in text
    assert "a.json" not in text and "b.json" in text
    assert install_agents_md(path, checkpoint="b.json") is False


def test_clinerules_orphan_begin_marker_keeps_human_text(tmp_path):
    rules = tmp_path / ".clinerules"
    rules.mkdir()
    (rules / "00-agent-handover.md").write_text(ORPHAN, encoding="utf-8")
    install_clinerules(rules, checkpoint="a.json")
    install_clinerules(rules, checkpoint="b.json")
    assert "human notes keep me" in (rules / "00-agent-handover.md").read_text(encoding="utf-8")


def test_splice_end_before_begin_appends():
    block = "<!-- agent-handover:begin -->X<!-- agent-handover:end -->"
    existing = "<!-- agent-handover:end -->\ntext\n"
    assert _agents_md.splice(existing, block).endswith(block + "\n")


def test_splice_orphan_end_reinstall_is_idempotent():
    # regression: an orphan END before the managed block made every re-install append a new block
    block = "<!-- agent-handover:begin -->X<!-- agent-handover:end -->"
    once = _agents_md.splice("<!-- agent-handover:end -->\ntext\n", block)
    assert _agents_md.splice(once, block) == once
    newer = "<!-- agent-handover:begin -->Y<!-- agent-handover:end -->"
    updated = _agents_md.splice(once, newer)
    assert updated.count("agent-handover:begin") == 1 and updated.endswith(newer + "\n")


def test_splice_empty_and_whitespace():
    assert _agents_md.splice("", "B") == "B\n"
    assert _agents_md.splice("  \n", "B") == "B\n"


# -- cli -----------------------------------------------------------------
def test_cli_requires_command():
    with pytest.raises(SystemExit):
        main([])


def test_cli_run_requires_config():
    with pytest.raises(SystemExit):
        main(["run"])


def test_cli_status_none(tmp_path, capsys):
    assert main(["status", "--checkpoint", str(tmp_path / "cp.json")]) == 0
    assert "status: none" in capsys.readouterr().out


def test_cli_run_no_push_then_check_completed(tmp_path, capsys):
    cfg = tmp_path / "h.toml"
    cfg.write_text(
        f'[handover]\nmemory_dir = "{(tmp_path / "m").as_posix()}"\n'
        '[backend]\ntype = "null"\n',
        encoding="utf-8",
    )
    cp = tmp_path / "cp.json"
    assert main(["run", "--config", str(cfg), "--note", "hi", "--no-push",
                 "--checkpoint", str(cp)]) == 0
    assert "session_note" in capsys.readouterr().out
    assert main(["check", "--checkpoint", str(cp)]) == RESUME_COMPLETED
