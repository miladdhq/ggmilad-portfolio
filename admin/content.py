"""The content model: what the panel edits and build.render() consumes.

Shape mirrors content.json exactly, so `Content.model_dump()` is what gets
written to disk and what the template receives.
"""
import hashlib
import json
import os
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class I18nText(Strict):
    fa: str = Field(min_length=1)
    en: str = Field(min_length=1)

    @field_validator("fa", "en")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must not be blank")
        return v


class OptionalLabel(Strict):
    fa: str = ""
    en: str = ""


class Link(Strict):
    url: str = ""
    label: OptionalLabel = OptionalLabel()

    @model_validator(mode="after")
    def _url_rules(self):
        if self.url:
            if not self.url.startswith("https://"):
                raise ValueError("link.url must start with https://")
            if not (self.label.fa.strip() and self.label.en.strip()):
                raise ValueError("a link needs both fa and en labels")
        return self


class Stat(Strict):
    value: str = Field(min_length=1)
    suffix: str = ""
    count: bool = False
    label: I18nText


class Progress(Strict):
    label: str = Field(min_length=1)
    percent: int = Field(ge=0, le=100)


class RoadmapItem(Strict):
    id: str = Field(pattern=r"^r\d+$")
    kind: Literal["active", "locked"]
    tag: str = Field(min_length=1)
    title: Optional[I18nText] = None
    body: I18nText
    progress: Optional[Progress] = None

    @model_validator(mode="after")
    def _active_has_title(self):
        if self.kind == "active" and self.title is None:
            raise ValueError("an active level needs a title")
        return self


class Project(Strict):
    id: str = Field(pattern=r"^p\d+$")
    mark: str = Field(min_length=1)
    tag: str = Field(min_length=1)
    badge: Literal["launch", "ship", "bot", "dev"]
    cat: Literal["web", "bot", "fun", "tool"]
    wide: bool = False
    extra_class: str = Field(default="", pattern=r"^[a-z0-9-]*$")
    hidden: bool = False
    chips: list[str] = []
    title: I18nText
    desc: I18nText
    link: Link = Link()

    @field_validator("chips")
    @classmethod
    def _clean_chips(cls, v: list[str]) -> list[str]:
        return [c.strip() for c in v if c and c.strip()]


class Site(Strict):
    donate_url: str = ""

    @field_validator("donate_url")
    @classmethod
    def _https(cls, v: str) -> str:
        if v and not v.startswith("https://"):
            raise ValueError("donate_url must start with https://")
        return v


class Content(Strict):
    site: Site = Site()
    stats: list[Stat] = Field(min_length=1, max_length=4)
    roadmap: list[RoadmapItem] = []
    projects: list[Project] = []

    @model_validator(mode="after")
    def _unique_ids(self):
        for name, items in (("projects", self.projects), ("roadmap", self.roadmap)):
            ids = [i.id for i in items]
            if len(ids) != len(set(ids)):
                raise ValueError(f"duplicate id in {name}")
        return self


def load_content(path: Path) -> Content:
    return Content.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))


def dumps(content: Content) -> str:
    return json.dumps(content.model_dump(), ensure_ascii=False, indent=2) + "\n"


def save_content(content: Content, path: Path) -> None:
    """Write via a sibling temp file and rename, so a crash never leaves half a file."""
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(dumps(content), encoding="utf-8")
    os.replace(tmp, path)


def content_hash(content: Content) -> str:
    canon = json.dumps(content.model_dump(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def next_project_id(content: Content) -> str:
    used = [int(p.id[1:]) for p in content.projects]
    return f"p{(max(used) + 1) if used else 1}"
