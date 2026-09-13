"""Where things live. Everything comes from the environment on the server;
tests build a Settings directly."""
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    repo_dir: Path        # git working copy: content.json, template.html, index.html
    live_index: Path      # the file nginx serves
    data_dir: Path        # backups/ and state.json
    password_hash: str
    session_secret: str
    git_sync: bool
    session_max_age: int = 12 * 3600
    backups_keep: int = 20

    @property
    def content_path(self) -> Path:
        return self.repo_dir / "content.json"

    @property
    def template_path(self) -> Path:
        return self.repo_dir / "template.html"

    @property
    def repo_index(self) -> Path:
        return self.repo_dir / "index.html"

    @property
    def backups_dir(self) -> Path:
        return self.data_dir / "backups"

    @property
    def state_path(self) -> Path:
        return self.data_dir / "state.json"


def settings_from_env(env=os.environ) -> Settings:
    repo = Path(env.get("GG_REPO_DIR", Path(__file__).resolve().parent.parent))
    return Settings(
        repo_dir=repo,
        live_index=Path(env.get("GG_LIVE_INDEX", repo / "data" / "live" / "index.html")),
        data_dir=Path(env.get("GG_DATA_DIR", repo / "data")),
        password_hash=env["ADMIN_PASSWORD_HASH"],
        session_secret=env["SESSION_SECRET"],
        git_sync=env.get("GG_GIT_SYNC", "1") == "1",
    )
