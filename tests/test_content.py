import copy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from admin.content import Content, content_hash, load_content, next_project_id, save_content

GOLD = json.loads((Path(__file__).parent / "fixtures" / "golden-content.json").read_text(encoding="utf-8"))


def gold():
    return copy.deepcopy(GOLD)


def test_golden_content_validates_and_roundtrips():
    c = Content.model_validate(gold())
    assert c.model_dump() == GOLD


def test_empty_translation_rejected():
    bad = gold()
    bad["projects"][0]["title"]["en"] = "  "
    with pytest.raises(ValidationError):
        Content.model_validate(bad)


@pytest.mark.parametrize("field,value", [("badge", "gold"), ("cat", "misc")])
def test_bad_enum_rejected(field, value):
    bad = gold()
    bad["projects"][0][field] = value
    with pytest.raises(ValidationError):
        Content.model_validate(bad)


def test_duplicate_id_rejected():
    bad = gold()
    bad["projects"][1]["id"] = bad["projects"][0]["id"]
    with pytest.raises(ValidationError):
        Content.model_validate(bad)


def test_http_link_rejected():
    bad = gold()
    bad["projects"][0]["link"] = {"url": "http://x.y", "label": {"fa": "a", "en": "b"}}
    with pytest.raises(ValidationError):
        Content.model_validate(bad)


def test_link_needs_label():
    bad = gold()
    bad["projects"][0]["link"] = {"url": "https://x.y", "label": {"fa": "", "en": ""}}
    with pytest.raises(ValidationError):
        Content.model_validate(bad)


def test_active_roadmap_needs_title():
    bad = gold()
    bad["roadmap"][0]["title"] = None
    with pytest.raises(ValidationError):
        Content.model_validate(bad)


def test_unknown_field_rejected():
    bad = gold()
    bad["projects"][0]["colour"] = "red"
    with pytest.raises(ValidationError):
        Content.model_validate(bad)


def test_chips_normalised():
    c = gold()
    c["projects"][0]["chips"] = [" Next.js ", "", "Prisma"]
    assert Content.model_validate(c).projects[0].chips == ["Next.js", "Prisma"]


def test_save_and_load_roundtrip(tmp_path):
    p = tmp_path / "content.json"
    c = Content.model_validate(gold())
    save_content(c, p)
    assert load_content(p) == c
    assert not list(tmp_path.glob("*.tmp"))


def test_hash_stable_and_sensitive():
    a = Content.model_validate(gold())
    b = Content.model_validate(gold())
    assert content_hash(a) == content_hash(b)
    b.projects[0].mark = "🧪"
    assert content_hash(a) != content_hash(b)


def test_next_project_id():
    assert next_project_id(Content.model_validate(gold())) == "p24"
