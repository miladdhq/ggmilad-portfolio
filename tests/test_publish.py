import shutil
import time
from pathlib import Path

import pytest

from admin.config import Settings
from admin.content import content_hash, load_content, save_content
from admin.publish import git_sync, list_backups, load_state, publish, restore

FIX = Path(__file__).parent / "fixtures"


def make_settings(tmp_path, git_sync=False, keep=3):
    repo = tmp_path / "repo"
    repo.mkdir()
    shutil.copy(FIX / "golden-content.json", repo / "content.json")
    shutil.copy(FIX / "golden-template.html", repo / "template.html")
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("OLD", encoding="utf-8")
    return Settings(
        repo_dir=repo, live_index=web / "index.html", data_dir=tmp_path / "data",
        password_hash="x", session_secret="s", git_sync=git_sync, backups_keep=keep,
    )


def test_publish_writes_live_and_repo_and_backup(tmp_path):
    s = make_settings(tmp_path)
    c = load_content(s.content_path)
    r = publish(s, c)
    live = s.live_index.read_text(encoding="utf-8")
    assert "<article" in live
    assert live == s.repo_index.read_text(encoding="utf-8")
    assert not list(s.live_index.parent.glob("*.new"))
    b = s.backups_dir / r["backup"]
    assert (b / "index.html").read_text(encoding="utf-8") == "OLD"
    assert (b / "content.json").exists()
    assert r["bytes"] == len(live.encode("utf-8"))
    assert load_state(s)["published_hash"] == content_hash(c)


def test_backups_pruned_to_keep(tmp_path):
    s = make_settings(tmp_path, keep=3)
    c = load_content(s.content_path)
    for _ in range(5):
        publish(s, c)
        time.sleep(1.05)
    assert len(list_backups(s)) == 3


def test_restore_swaps_both_files(tmp_path):
    s = make_settings(tmp_path)
    c = load_content(s.content_path)
    publish(s, c)
    c.projects[0].mark = "🧪"
    save_content(c, s.content_path)
    time.sleep(1.05)
    second = publish(s, c)
    assert "🧪" in s.live_index.read_text(encoding="utf-8")
    # that backup holds the state from BEFORE the second publish
    restore(s, second["backup"])
    assert "🧪" not in s.live_index.read_text(encoding="utf-8")
    assert load_content(s.content_path).projects[0].mark != "🧪"
    assert load_state(s)["published_hash"] == content_hash(load_content(s.content_path))
    assert load_state(s)["restored_from"] == second["backup"]


def test_restore_rejects_bad_name(tmp_path):
    s = make_settings(tmp_path)
    with pytest.raises(ValueError):
        restore(s, "../etc")
    with pytest.raises(FileNotFoundError):
        restore(s, "20260101T000000Z")


class FakeRun:
    """Stands in for subprocess.run; fails `fails` pushes then succeeds."""

    def __init__(self, fails):
        self.fails = fails
        self.calls = []

    def __call__(self, cmd, **kw):
        self.calls.append(cmd)
        if cmd[:2] == ["git", "push"] and self.fails > 0:
            self.fails -= 1
            return type("P", (), {"returncode": 1, "stderr": "net down", "stdout": ""})()
        return type("P", (), {"returncode": 0, "stderr": "", "stdout": ""})()


def test_git_sync_retries_then_records(tmp_path):
    s = make_settings(tmp_path)
    r = FakeRun(fails=2)
    out = git_sync(s, "msg", runner=r, attempts=3, delay=0)
    assert out["ok"]
    assert sum(1 for c in r.calls if c[:2] == ["git", "push"]) == 3
    assert r.calls[0][:2] == ["git", "add"] and r.calls[1][:2] == ["git", "commit"]
    assert load_state(s)["git_sync"]["ok"]


def test_git_sync_gives_up_and_records_error(tmp_path):
    s = make_settings(tmp_path)
    out = git_sync(s, "msg", runner=FakeRun(fails=5), attempts=3, delay=0)
    assert not out["ok"] and "net down" in out["error"]
    assert not load_state(s)["git_sync"]["ok"]
