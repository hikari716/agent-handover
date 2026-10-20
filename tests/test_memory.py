import pytest

from agent_handover.memory import MemoryStore


def test_layer1_is_dated_and_tagged(tmp_path):
    store = MemoryStore(tmp_path)
    p = store.write(1, "session notes", tag="refactor", date_str="2026-06-07")
    assert p == tmp_path / "layer1" / "2026-06" / "refactor-2026-06-07.md"
    assert "session notes" in p.read_text()


def test_layer2_is_always_overwritten(tmp_path):
    store = MemoryStore(tmp_path)
    store.write(2, "state v1")
    p = store.write(2, "state v2")
    assert p.read_text().endswith("state v2")
    assert store.read_latest(2).endswith("state v2")


def test_layer3_monthly_archive_path(tmp_path):
    store = MemoryStore(tmp_path)
    p = store.write(3, "archive", tag="projx", date_str="2026-05-31")
    assert p.name == "2026-05-projx-archive.md"


def test_read_latest_falls_back_to_empty(tmp_path):
    store = MemoryStore(tmp_path)
    assert store.read_latest(1) == ""
    assert store.read_latest(2) == ""


def test_read_latest_filters_by_tag(tmp_path):
    store = MemoryStore(tmp_path)
    store.write(1, "alpha note", tag="alpha", date_str="2026-06-01")
    store.write(1, "beta note", tag="beta", date_str="2026-06-02")
    assert "alpha note" in store.read_latest(1, tag="alpha")


def test_invalid_layer_raises(tmp_path):
    with pytest.raises(ValueError):
        MemoryStore(tmp_path).write(4, "nope")


def test_dry_run_writes_nothing(tmp_path):
    store = MemoryStore(tmp_path)
    p = store.write(1, "x", dry_run=True)
    assert not p.exists()


def test_layer1_note_count(tmp_path):
    store = MemoryStore(tmp_path)
    store.write(1, "a", tag="t1", date_str="2026-06-01")
    store.write(1, "b", tag="t2", date_str="2026-06-02")
    assert store.layer1_note_count() == 2
    assert store.layer1_note_count("2026-06") == 2


def test_layer1_appends_same_day_sessions(tmp_path):
    # README / module docstring: Layer 1 is "append, dated" — a second session
    # with the same tag on the same day must not erase the first one's note.
    store = MemoryStore(tmp_path)
    p1 = store.write(1, "morning session", tag="t", date_str="2026-06-07")
    p2 = store.write(1, "evening session", tag="t", date_str="2026-06-07")
    assert p1 == p2
    text = p1.read_text(encoding="utf-8")
    assert "morning session" in text and "evening session" in text
    assert text.index("morning session") < text.index("evening session")
    assert text.count("<!-- agent-handover | layer1 | 2026-06-07 -->") == 2
    assert store.layer1_note_count() == 1
