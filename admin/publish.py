"""Publish = render, back up, atomically replace the live file, then push
to GitHub in the background. Restore swaps a backup back in, content and
site together, so the two never drift apart.

The write ritual is the same one every by-hand deploy of this site used:
write `index.html.new` next to the live file, then rename over it.
"""
import json
import os
import re
import shutil
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from build import render
from admin.config import Settings
from admin.content import Content, content_hash, dumps, load_content, save_content

BACKUP_NAME = re.compile(r"^\d{8}T\d{6}Z(?:-\d+)?$")


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".new")
    tmp.write_text(text, encoding="utf-8")
    os.chmod(tmp, 0o644)
    os.replace(tmp, path)


def load_state(s: Settings) -> dict:
    try:
        return json.loads(s.state_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


def _update_state(s: Settings, **kw) -> dict:
    st = load_state(s)
    st.update(kw)
    _atomic_write(s.state_path, json.dumps(st, ensure_ascii=False, indent=2))
    return st


def _published_content(s: Settings) -> Path:
    """The content that produced the live index — not the draft, which may be ahead of it."""
    return s.data_dir / "published-content.json"


def _snapshot(s: Settings) -> Path:
    """Copy the live index + the content that built it into a fresh backup folder."""
    stamp = utc_stamp()
    d = s.backups_dir / stamp
    n = 1
    while d.exists():  # two snapshots in one second must not share a folder
        n += 1
        d = s.backups_dir / f"{stamp}-{n}"
    d.mkdir(parents=True)
    if s.live_index.exists():
        shutil.copy2(s.live_index, d / "index.html")
    src = _published_content(s) if _published_content(s).exists() else s.content_path
    if src.exists():
        shutil.copy2(src, d / "content.json")
    return d


def _backup_dirs(s: Settings) -> list[Path]:
    if not s.backups_dir.exists():
        return []
    return sorted((p for p in s.backups_dir.iterdir() if p.is_dir() and BACKUP_NAME.match(p.name)), reverse=True)


def _prune(s: Settings) -> None:
    for old in _backup_dirs(s)[s.backups_keep:]:
        shutil.rmtree(old)


def list_backups(s: Settings) -> list[dict]:
    out = []
    for p in _backup_dirs(s):
        idx = p / "index.html"
        out.append({
            "name": p.name,
            "bytes": idx.stat().st_size if idx.exists() else 0,
            "has_content": (p / "content.json").exists(),
        })
    return out


def publish(s: Settings, content: Content, runner=subprocess.run) -> dict:
    html = render(content.model_dump(), s.template_path)
    backup = _snapshot(s)
    _atomic_write(s.live_index, html)
    _atomic_write(s.repo_index, html)
    _atomic_write(_published_content(s), dumps(content))
    _prune(s)
    size = len(html.encode("utf-8"))
    _update_state(s, last_publish=backup.name, last_publish_bytes=size, published_hash=content_hash(content))
    if s.git_sync:
        threading.Thread(
            target=git_sync, args=(s, f"Publish from admin panel — {backup.name}", runner), daemon=True,
        ).start()
    return {"timestamp": backup.name, "backup": backup.name, "bytes": size}


def restore(s: Settings, name: str) -> dict:
    if not BACKUP_NAME.match(name or ""):
        raise ValueError("bad backup name")
    src = s.backups_dir / name
    if not (src / "index.html").exists():
        raise FileNotFoundError(name)
    current = _snapshot(s)
    html = (src / "index.html").read_text(encoding="utf-8")
    _atomic_write(s.live_index, html)
    _atomic_write(s.repo_index, html)
    if (src / "content.json").exists():
        restored = load_content(src / "content.json")
        save_content(restored, s.content_path)
        _atomic_write(_published_content(s), dumps(restored))
    _prune(s)
    _update_state(
        s, last_publish=current.name, last_publish_bytes=len(html.encode("utf-8")),
        published_hash=content_hash(load_content(s.content_path)), restored_from=name,
    )
    return {"restored": name, "backup": current.name}


def git_sync(s: Settings, message: str, runner=subprocess.run, attempts: int = 3, delay: float = 5.0) -> dict:
    """Commit content.json + index.html and push, retrying the push. Never raises;
    the outcome is recorded in state.json for the panel to show."""

    def run(*cmd):
        return runner(list(cmd), cwd=str(s.repo_dir), capture_output=True, text=True)

    err = ""
    try:
        run("git", "add", "content.json", "index.html")
        run("git", "commit", "-q", "-m", message)  # non-zero when nothing changed; that's fine
        for i in range(attempts):
            p = run("git", "push", "-q")
            if p.returncode == 0:
                out = {"ok": True, "at": utc_stamp(), "error": ""}
                _update_state(s, git_sync=out)
                return out
            err = (p.stderr or p.stdout or "").strip()[-400:]
            if i + 1 < attempts:
                time.sleep(delay)
    except Exception as e:  # git missing, repo not a clone, ...
        err = f"{type(e).__name__}: {e}"[-400:]
    out = {"ok": False, "at": utc_stamp(), "error": err or "push failed"}
    _update_state(s, git_sync=out)
    return out
