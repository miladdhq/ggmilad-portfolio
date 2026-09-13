"""Render index.html from content.json + template.html.

    python build.py [content.json] [template.html] > index.html

The same `render()` runs inside the admin panel on Publish, so the site
built by hand and the site built by the panel are byte-for-byte the same.
"""
import json
import sys
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

# Persian badge captions as they appear in the static markup. The I18N
# dictionaries keep their own literal copies of these under `badge.*`.
BADGE_FA = {
    "launch": "🚀 آماده لانچ",
    "ship": "✅ شیپ شده",
    "bot": "🤖 فعال",
    "dev": "🛠 در حال ساخت",
}


def js_string(value) -> str:
    """A JS string literal that is safe inside an inline <script>."""
    s = json.dumps(str(value), ensure_ascii=False)
    return s.replace("</", "<\\/").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")


def i18n_lines(content: dict, lang: str) -> str:
    """The generated half of one I18N dictionary: stats, projects, roadmap."""
    out = []
    for i, s in enumerate(content["stats"], 1):
        out.append(f"      'hero.stat{i}':{js_string(s['label'][lang])},")
    for p in content["projects"]:
        if p.get("hidden"):
            continue
        out.append(f"      '{p['id']}.t':{js_string(p['title'][lang])},")
        out.append(f"      '{p['id']}.d':{js_string(p['desc'][lang])},")
        link = p.get("link") or {}
        if link.get("url"):
            out.append(f"      '{p['id']}.cta':{js_string(link['label'][lang])},")
    for i, r in enumerate(content["roadmap"], 1):
        if r["kind"] == "active":
            out.append(f"      'road.t{i}':{js_string(r['title'][lang])},")
        out.append(f"      'road.d{i}':{js_string(r['body'][lang])},")
    return "\n".join(out)


def render(content: dict, template_path: Path) -> str:
    template_path = Path(template_path)
    env = Environment(
        loader=FileSystemLoader(str(template_path.parent)),
        autoescape=select_autoescape(["html"]),
        keep_trailing_newline=True,
    )
    env.filters["js_string"] = js_string
    tpl = env.get_template(template_path.name)
    return tpl.render(
        site=content["site"],
        stats=content["stats"],
        roadmap=content["roadmap"],
        projects=[p for p in content["projects"] if not p.get("hidden")],
        badge_fa=BADGE_FA,
        i18n_fa=i18n_lines(content, "fa"),
        i18n_en=i18n_lines(content, "en"),
    )


if __name__ == "__main__":
    content_path = Path(sys.argv[1] if len(sys.argv) > 1 else "content.json")
    template_path = Path(sys.argv[2] if len(sys.argv) > 2 else "template.html")
    sys.stdout.write(render(json.loads(content_path.read_text(encoding="utf-8")), template_path))
