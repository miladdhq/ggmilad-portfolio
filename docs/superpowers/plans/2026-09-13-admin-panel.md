# Admin Panel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A password-protected panel at `https://ggon.top/admin` that edits the portfolio's projects, roadmap, hero stats and donate URL in a `content.json`, and regenerates the static `index.html` on Publish.

**Architecture:** `index.html` is split once (by `tools/migrate.py`) into `template.html` (design, Jinja loops for the three editable regions) and `content.json` (data). `build.render()` joins them. A FastAPI app (`admin/`) serves a single-file UI, validates content with pydantic, writes the JSON atomically, and on Publish backs up, atomically replaces the live file, and pushes to GitHub in the background. The public site stays a static file with no runtime dependency.

**Tech Stack:** Python 3.12 · FastAPI · uvicorn · Jinja2 · pydantic v2 · argon2-cffi · itsdangerous · pytest + httpx (TestClient) · systemd · nginx.

**Spec:** `docs/superpowers/specs/2026-09-13-admin-panel-design.md`

## Global Constraints

- Public site stays one static `index.html` served by nginx; the app never serves ggon.top itself.
- App listens on `127.0.0.1:9914`, one worker, routes under `/admin`.
- Cookie `gg_admin`: HttpOnly, Secure, SameSite=Strict, path `/admin`, 12 h.
- Every mutating route needs the cookie **and** header `X-Requested-With: ggmilad-admin`.
- Login lockout: 5 failures per IP → 15 minutes.
- Backups: `data/backups/<UTC ts>/{index.html,content.json}`, keep 20.
- `badge ∈ {launch, ship, bot, dev}`, `cat ∈ {web, bot, fun, tool}`, `roadmap.kind ∈ {active, locked}`.
- Every `fa`/`en` text non-empty; links `https://` only.
- Secrets (`ADMIN_PASSWORD_HASH`, `SESSION_SECRET`) only in `.env`, never committed.
- Server user `ggadmin`; repo at `/opt/ggmilad-admin`; live file `/var/www/ggmilad/index.html` (ggadmin:www-data 664, dir 775).
- Commit messages end with the session's Co-Authored-By / Claude-Session lines.

---

### Task 1: Scaffolding, golden fixtures, migration, build — the lossless split

**Files:**
- Create: `requirements.txt`, `requirements-dev.txt`, `pytest.ini`
- Modify: `.gitignore` (append)
- Create: `tests/fixtures/golden-index.html` (copy of current `index.html`)
- Create: `tests/test_golden.py`
- Create: `tools/migrate.py`
- Create: `build.py`
- Generated + committed: `content.json`, `template.html`, `tests/fixtures/golden-content.json`, `tests/fixtures/golden-template.html`

**Interfaces:**
- Produces: `build.render(content: dict, template_path: Path) -> str`; `build.js_string(value) -> str`; `build.BADGE_FA: dict[str,str]`; `tools.migrate.extract(html: str) -> dict` and `tools.migrate.make_template(html: str) -> str`; the `content.json` shape from the spec, with the extra optional project field `extra_class: str` (carries `card-donate`).

- [ ] **Step 1: Scaffolding**

`requirements.txt`:
```
fastapi==0.115.*
uvicorn[standard]==0.30.*
jinja2==3.1.*
pydantic==2.*
argon2-cffi==23.*
itsdangerous==2.*
python-multipart==0.0.*
```
`requirements-dev.txt`: `-r requirements.txt`, `pytest==8.*`, `httpx==0.27.*`.
`pytest.ini`: `[pytest]\ntestpaths = tests\n`.
Append to `.gitignore`: `.venv/`, `.env`, `data/`, `__pycache__/`, `.pytest_cache/`, `*.pyc`.
Then `python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt`.

- [ ] **Step 2: Freeze the golden fixture**

`cp index.html tests/fixtures/golden-index.html`. This copy never changes again; it is what "lossless" means.

- [ ] **Step 3: Write the failing golden test**

```python
# tests/test_golden.py
import json, re
from pathlib import Path
from build import render
from tools.migrate import extract, make_template

FIX = Path(__file__).parent / "fixtures"
GOLD = (FIX / "golden-index.html").read_text(encoding="utf-8")

STR = r"""'(?P<k>[^']+)':(?P<v>'(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*")"""

def _js_decode(lit: str) -> str:
    body = lit[1:-1]
    def sub(m):
        c = m.group(1)
        if c == "n": return "\n"
        if c == "u": return chr(int(m.group(2), 16))
        return c
    return re.sub(r"\\(u)([0-9a-fA-F]{4})|\\(.)", lambda m: sub(type("M",(),{"group":lambda s,i:(m.group(3) if i==1 else m.group(2)) if m.group(3) else m.group(i)})()) if False else _unescape(m), body)

def _unescape(m):
    if m.group(1) == "u": return chr(int(m.group(2), 16))
    c = m.group(3)
    return {"n": "\n", "t": "\t"}.get(c, c)

def i18n(html: str) -> dict:
    start = html.index("var I18N={"); end = html.index("\n  };", start)
    block = html[start:end]
    fa_i = block.index("fa:{"); en_i = block.index("en:{")
    out = {}
    for lang, seg in (("fa", block[fa_i:en_i]), ("en", block[en_i:])):
        out[lang] = {m.group("k"): _js_decode(m.group("v")) for m in re.finditer(STR, seg)}
    return out

def markup(html: str) -> str:
    start = html.index("var I18N={"); end = html.index("\n  };", start)
    html = html[:start] + "I18N" + html[end:]
    html = re.sub(r"\s+", " ", html)
    return re.sub(r">\s+<", "><", html).strip()

def test_render_reproduces_golden_markup():
    content = extract(GOLD); template = make_template(GOLD)
    (FIX / "golden-template.html").write_text(template, encoding="utf-8")
    out = render(content, FIX / "golden-template.html")
    assert markup(out) == markup(GOLD)

def test_render_reproduces_golden_i18n():
    content = extract(GOLD); template = make_template(GOLD)
    (FIX / "golden-template.html").write_text(template, encoding="utf-8")
    out = render(content, FIX / "golden-template.html")
    assert i18n(out) == i18n(GOLD)

def test_committed_split_matches_migration():
    assert json.loads((FIX / "golden-content.json").read_text(encoding="utf-8")) == extract(GOLD)
    assert (FIX / "golden-template.html").read_text(encoding="utf-8") == make_template(GOLD)
```
(Simplify `_js_decode` to a single `re.sub(r"\\(u)([0-9a-fA-F]{4})|\\(.)", _unescape, body)` — the tangled lambda above is exactly what not to write; the executor uses the clean form.)

- [ ] **Step 4: Run it, expect ImportError** — `.venv/bin/pytest tests/test_golden.py -q`.

- [ ] **Step 5: Write `build.py`**

```python
"""Render index.html from content.json + template.html.
CLI: python build.py [content.json] [template.html] > index.html"""
import json, sys
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, select_autoescape

BADGE_FA = {"launch": "🚀 آماده لانچ", "ship": "✅ شیپ شده", "bot": "🤖 فعال", "dev": "🛠 در حال ساخت"}

def js_string(value) -> str:
    """A JS string literal that is safe inside an inline <script>."""
    s = json.dumps(str(value), ensure_ascii=False)
    return s.replace("</", "<\\/").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")

def i18n_lines(content: dict, lang: str) -> str:
    out = []
    for i, s in enumerate(content["stats"], 1):
        out.append(f"      'hero.stat{i}':{js_string(s['label'][lang])},")
    for p in content["projects"]:
        if p.get("hidden"): continue
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
    env = Environment(loader=FileSystemLoader(str(template_path.parent)),
                      autoescape=select_autoescape(["html"]), keep_trailing_newline=True)
    env.filters["js_string"] = js_string
    tpl = env.get_template(template_path.name)
    return tpl.render(site=content["site"], stats=content["stats"], roadmap=content["roadmap"],
                      projects=[p for p in content["projects"] if not p.get("hidden")],
                      badge_fa=BADGE_FA, i18n_fa=i18n_lines(content, "fa"), i18n_en=i18n_lines(content, "en"))

if __name__ == "__main__":
    c = Path(sys.argv[1] if len(sys.argv) > 1 else "content.json")
    t = Path(sys.argv[2] if len(sys.argv) > 2 else "template.html")
    sys.stdout.write(render(json.loads(c.read_text(encoding="utf-8")), t))
```

- [ ] **Step 6: Write `tools/migrate.py`**

Line-based on the golden HTML. Regions are found by their opening line and the next line that is exactly `  </div>` (two-space indent):
`  <div class="hero-stats fadeup d7">`, `  <div class="projects-grid" id="projectsGrid">`, `  <div class="roadmap-grid">`. The I18N dict spans from the line `  var I18N={` to the line `  };`; `    en:{` splits fa from en.

```python
"""One-time split of index.html into content.json + template.html.
python tools/migrate.py index.html   -> writes content.json and template.html"""
import json, re, sys
from pathlib import Path

STR = r"""'(?P<k>[^']+)':(?P<v>'(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*")"""
ARTICLE = re.compile(r'''<article class="card(?P<cls>[^"]*)" data-cat="(?P<cat>[a-z]+)">\s*
<div class="card-mark">(?P<mark>.*?)</div>\s*
<div class="card-top"><span class="card-tag">(?P<tag>.*?)</span><span class="badge badge-(?P<badge>[a-z]+)" data-i18n="badge\.[a-z]+">.*?</span></div>\s*
<h3 data-i18n="(?P<id>p\d+)\.t">(?P<title>.*?)</h3>\s*
<p data-i18n="(?P=id)\.d">(?P<desc>.*?)</p>\s*
<div class="chips">(?P<chips>.*?)</div>\s*
(?:<a class="card-link" href="(?P<url>[^"]*)"[^>]*><span data-i18n="(?P=id)\.cta">(?P<cta>.*?)</span><span class="ltr">↗</span></a>\s*)?
</article>'''.replace("\n", r"\s*"), re.S)
STAT = re.compile(r'<div class="hstat"><b class="mono"(?: data-count="(?P<count>\d+)" data-suffix="(?P<suffix>[^"]*)")?>(?P<text>.*?)</b><span data-i18n="hero\.stat\d">(?P<label>.*?)</span></div>')
ACTIVE = re.compile(r'<div class="level level-active reveal">\s*<span class="level-tag">(?P<tag>.*?)</span>\s*<h3 data-i18n="road\.t(?P<n>\d)">(?P<title>.*?)</h3>\s*<p data-i18n="road\.d\d">(?P<body>.*?)</p>\s*<div class="progress">\s*<div class="progress-info"><span>(?P<plabel>.*?)</span><span>(?P<pct>\d+)%</span></div>.*?</div>\s*</div>\s*</div>', re.S)
LOCKED = re.compile(r'<div class="level level-locked reveal">\s*<span class="lock">🔒</span>\s*<span class="level-tag">(?P<tag>.*?)</span>\s*<h3 data-i18n="road\.locked">.*?</h3>\s*<p class="hint" data-i18n="road\.d(?P<n>\d)">(?P<body>.*?)</p>\s*</div>', re.S)
GEN_KEY = re.compile(r"\s*'(p\d+\.(t|d|cta)|road\.[td]\d|hero\.stat\d)':")

def _unescape(m):
    if m.group(1) == "u": return chr(int(m.group(2), 16))
    return {"n": "\n", "t": "\t"}.get(m.group(3), m.group(3))

def js_decode(lit): return re.sub(r"\\(u)([0-9a-fA-F]{4})|\\(.)", _unescape, lit[1:-1])

def region(lines, opener):
    start = lines.index(opener)
    end = next(i for i in range(start + 1, len(lines)) if lines[i] == "  </div>")
    return start, end            # lines[start+1:end] is the body

def dict_bounds(lines):
    a = lines.index("  var I18N={"); b = lines.index("  };", a); e = lines.index("    en:{", a)
    return a, e, b

def i18n_dicts(lines):
    a, e, b = dict_bounds(lines)
    fa = "\n".join(lines[a:e]); en = "\n".join(lines[e:b])
    return ({m.group("k"): js_decode(m.group("v")) for m in re.finditer(STR, fa)},
            {m.group("k"): js_decode(m.group("v")) for m in re.finditer(STR, en)})

def extract(html: str) -> dict:
    lines = html.split("\n"); fa, en = i18n_dicts(lines)
    t = lambda k: {"fa": fa[k], "en": en[k]}
    s0, s1 = region(lines, '  <div class="hero-stats fadeup d7">')
    stats = []
    for m in STAT.finditer("\n".join(lines[s0 + 1:s1])):
        n = len(stats) + 1
        if m.group("count"): stats.append({"value": m.group("count"), "suffix": m.group("suffix"), "count": True, "label": t(f"hero.stat{n}")})
        else: stats.append({"value": m.group("text"), "suffix": "", "count": False, "label": t(f"hero.stat{n}")})
    p0, p1 = region(lines, '  <div class="projects-grid" id="projectsGrid">')
    body = "\n".join(lines[p0 + 1:p1]); projects = []
    for m in ARTICLE.finditer(body):
        cls = m.group("cls").split(); extra = [c for c in cls if c not in ("wide", "reveal")]
        pid = m.group("id")
        p = {"id": pid, "mark": m.group("mark"), "tag": m.group("tag"), "badge": m.group("badge"), "cat": m.group("cat"),
             "wide": "wide" in cls, "extra_class": extra[0] if extra else "", "hidden": False,
             "chips": re.findall(r'<span class="chip">(.*?)</span>', m.group("chips")),
             "title": t(f"{pid}.t"), "desc": t(f"{pid}.d"),
             "link": {"url": m.group("url") or "", "label": t(f"{pid}.cta") if m.group("url") else {"fa": "", "en": ""}}}
        projects.append(p)
    if len(projects) != body.count("<article"): raise SystemExit("unparsed article in projects grid")
    r0, r1 = region(lines, '  <div class="roadmap-grid">'); rb = "\n".join(lines[r0 + 1:r1]); roadmap = []
    for m in sorted(list(ACTIVE.finditer(rb)) + list(LOCKED.finditer(rb)), key=lambda m: m.start()):
        n = m.group("n")
        if "level-active" in m.group(0):
            roadmap.append({"id": f"r{n}", "kind": "active", "tag": m.group("tag"), "title": t(f"road.t{n}"), "body": t(f"road.d{n}"),
                            "progress": {"label": m.group("plabel"), "percent": int(m.group("pct"))}})
        else:
            roadmap.append({"id": f"r{n}", "kind": "locked", "tag": m.group("tag"), "title": None, "body": t(f"road.d{n}"), "progress": None})
    donate = re.search(r'href="(https://donate\.ggon\.top)"', html)
    return {"site": {"donate_url": donate.group(1) if donate else ""}, "stats": stats, "roadmap": roadmap, "projects": projects}

STATS_TPL = '''{% for s in stats %}    <div class="hstat"><b class="mono"{% if s.count %} data-count="{{ s.value }}" data-suffix="{{ s.suffix }}"{% endif %}>{{ s.value }}{{ s.suffix }}</b><span data-i18n="hero.stat{{ loop.index }}">{{ s.label.fa }}</span></div>
{% endfor %}'''
PROJECTS_TPL = '''{% for p in projects %}
    <article class="card{% if p.wide %} wide{% endif %}{% if p.extra_class %} {{ p.extra_class }}{% endif %} reveal" data-cat="{{ p.cat }}">
      <div class="card-mark">{{ p.mark }}</div>
      <div class="card-top"><span class="card-tag">{{ p.tag }}</span><span class="badge badge-{{ p.badge }}" data-i18n="badge.{{ p.badge }}">{{ badge_fa[p.badge] }}</span></div>
      <h3 data-i18n="{{ p.id }}.t">{{ p.title.fa|safe }}</h3>
      <p data-i18n="{{ p.id }}.d">{{ p.desc.fa|safe }}</p>
      <div class="chips">{% for c in p.chips %}<span class="chip">{{ c }}</span>{% endfor %}</div>
{% if p.link and p.link.url %}      <a class="card-link" href="{{ p.link.url }}" target="_blank" rel="noopener noreferrer"><span data-i18n="{{ p.id }}.cta">{{ p.link.label.fa }}</span><span class="ltr">↗</span></a>
{% endif %}    </article>
{% endfor %}'''
ROADMAP_TPL = '''{% for r in roadmap %}{% if r.kind == 'active' %}
    <div class="level level-active reveal">
      <span class="level-tag">{{ r.tag }}</span>
      <h3 data-i18n="road.t{{ loop.index }}">{{ r.title.fa|safe }}</h3>
      <p data-i18n="road.d{{ loop.index }}">{{ r.body.fa|safe }}</p>
{% if r.progress %}      <div class="progress">
        <div class="progress-info"><span>{{ r.progress.label }}</span><span>{{ r.progress.percent }}%</span></div>
        <div class="progress-bar"><div class="progress-fill" data-w="{{ r.progress.percent }}" style="width:{{ r.progress.percent }}%"></div></div>
      </div>
{% endif %}    </div>
{% else %}
    <div class="level level-locked reveal">
      <span class="lock">🔒</span>
      <span class="level-tag">{{ r.tag }}</span>
      <h3 data-i18n="road.locked">؟ ؟ ؟</h3>
      <p class="hint" data-i18n="road.d{{ loop.index }}">{{ r.body.fa|safe }}</p>
    </div>
{% endif %}{% endfor %}'''

def make_template(html: str) -> str:
    lines = html.split("\n")
    if "{{" in html or "{%" in html: raise SystemExit("index.html already contains Jinja delimiters")
    # regions, last-first so earlier indices stay valid
    for opener, tpl in (('  <div class="roadmap-grid">', ROADMAP_TPL),
                        ('  <div class="projects-grid" id="projectsGrid">', PROJECTS_TPL),
                        ('  <div class="hero-stats fadeup d7">', STATS_TPL)):
        a, b = region(lines, opener); lines[a + 1:b] = [tpl.rstrip("\n")]
    a, e, b = dict_bounds(lines)
    out, placed = [], {"fa": False, "en": False}
    for i, ln in enumerate(lines):
        if a < i < b and GEN_KEY.match(ln):
            lang = "fa" if i < e else "en"
            if not placed[lang]: out.append("{{ i18n_%s }}" % lang); placed[lang] = True
            continue
        out.append(ln)
    lines = out
    for i, ln in enumerate(lines):
        if 'href="https://donate.ggon.top"' in ln and "card-link" not in ln:
            lines[i] = "{% if site.donate_url %}" + ln.replace('href="https://donate.ggon.top"', 'href="{{ site.donate_url }}"') + "{% endif %}"
    return "\n".join(lines)

if __name__ == "__main__":
    src = Path(sys.argv[1] if len(sys.argv) > 1 else "index.html"); html = src.read_text(encoding="utf-8")
    Path("content.json").write_text(json.dumps(extract(html), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    Path("template.html").write_text(make_template(html), encoding="utf-8")
    print("wrote content.json and template.html")
```
Note `'i18n_%s' % lang` inside the string must produce `{{ i18n_fa }}` — write it with explicit braces so the `%` formatting does not eat them.

- [ ] **Step 7: Run the golden tests until they pass** — `.venv/bin/pytest tests/test_golden.py -v`. Fix regexes against the real file until markup and i18n both match. Then `cp tests/fixtures/golden-template.html template.html` is NOT how the repo template is made — run `python tools/migrate.py index.html` at the repo root to write `content.json` and `template.html`, and `cp content.json tests/fixtures/golden-content.json`. Run `python build.py > /tmp/check.html && diff <(...)` is unnecessary: the tests are the check.

- [ ] **Step 8: Commit** — `git add requirements*.txt pytest.ini .gitignore build.py tools/migrate.py content.json template.html tests/` · message `Split index.html into content.json + template.html with a lossless golden test`.

---

### Task 2: Content schema and atomic storage — `admin/content.py`

**Files:** Create `admin/__init__.py`, `admin/content.py`, `tests/test_content.py`.

**Interfaces:**
- Produces: `Content` (pydantic model with `.model_dump()` matching the JSON shape), `load_content(path: Path) -> Content`, `save_content(content: Content, path: Path) -> None` (atomic), `content_hash(content: Content) -> str` (sha256 hex of canonical JSON), `next_project_id(content: Content) -> str`.

- [ ] **Step 1: Failing tests**

```python
# tests/test_content.py
import json, pytest
from pathlib import Path
from pydantic import ValidationError
from admin.content import Content, load_content, save_content, content_hash, next_project_id

GOLD = json.loads((Path(__file__).parent / "fixtures" / "golden-content.json").read_text(encoding="utf-8"))

def test_golden_content_validates():
    c = Content.model_validate(GOLD)
    assert c.model_dump() == GOLD

def test_empty_translation_rejected():
    bad = json.loads(json.dumps(GOLD)); bad["projects"][0]["title"]["en"] = "  "
    with pytest.raises(ValidationError): Content.model_validate(bad)

@pytest.mark.parametrize("field,value", [("badge", "gold"), ("cat", "misc")])
def test_bad_enum_rejected(field, value):
    bad = json.loads(json.dumps(GOLD)); bad["projects"][0][field] = value
    with pytest.raises(ValidationError): Content.model_validate(bad)

def test_duplicate_id_rejected():
    bad = json.loads(json.dumps(GOLD)); bad["projects"][1]["id"] = bad["projects"][0]["id"]
    with pytest.raises(ValidationError): Content.model_validate(bad)

def test_http_link_rejected():
    bad = json.loads(json.dumps(GOLD)); bad["projects"][0]["link"] = {"url": "http://x.y", "label": {"fa": "a", "en": "b"}}
    with pytest.raises(ValidationError): Content.model_validate(bad)

def test_link_needs_label():
    bad = json.loads(json.dumps(GOLD)); bad["projects"][0]["link"] = {"url": "https://x.y", "label": {"fa": "", "en": ""}}
    with pytest.raises(ValidationError): Content.model_validate(bad)

def test_active_roadmap_needs_title():
    bad = json.loads(json.dumps(GOLD)); bad["roadmap"][0]["title"] = None
    with pytest.raises(ValidationError): Content.model_validate(bad)

def test_chips_normalised():
    c = json.loads(json.dumps(GOLD)); c["projects"][0]["chips"] = [" Next.js ", "", "Prisma"]
    assert Content.model_validate(c).projects[0].chips == ["Next.js", "Prisma"]

def test_save_and_load_roundtrip(tmp_path):
    p = tmp_path / "content.json"; c = Content.model_validate(GOLD)
    save_content(c, p); assert load_content(p) == c
    assert not list(tmp_path.glob("*.tmp"))

def test_hash_stable_and_sensitive():
    a = Content.model_validate(GOLD); b = Content.model_validate(GOLD)
    assert content_hash(a) == content_hash(b)
    b.projects[0].mark = "🧪"; assert content_hash(a) != content_hash(b)

def test_next_project_id():
    assert next_project_id(Content.model_validate(GOLD)) == "p24"
```

- [ ] **Step 2: Run, expect ImportError.**

- [ ] **Step 3: Implement**

```python
# admin/content.py
"""The content model: what the panel edits and build.render() consumes."""
import hashlib, json, os, re
from pathlib import Path
from typing import Literal, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")

class I18nText(Strict):
    fa: str = Field(min_length=1); en: str = Field(min_length=1)
    @field_validator("fa", "en")
    @classmethod
    def _not_blank(cls, v):
        if not v.strip(): raise ValueError("must not be blank")
        return v

class OptionalLabel(Strict):
    fa: str = ""; en: str = ""

class Link(Strict):
    url: str = ""; label: OptionalLabel = OptionalLabel()
    @model_validator(mode="after")
    def _url_rules(self):
        if self.url:
            if not self.url.startswith("https://"): raise ValueError("link.url must start with https://")
            if not (self.label.fa.strip() and self.label.en.strip()): raise ValueError("link.label needs fa and en")
        return self

class Stat(Strict):
    value: str = Field(min_length=1); suffix: str = ""; count: bool = False; label: I18nText

class Progress(Strict):
    label: str = Field(min_length=1); percent: int = Field(ge=0, le=100)

class RoadmapItem(Strict):
    id: str = Field(pattern=r"^r\d+$"); kind: Literal["active", "locked"]; tag: str = Field(min_length=1)
    title: Optional[I18nText] = None; body: I18nText; progress: Optional[Progress] = None
    @model_validator(mode="after")
    def _active_has_title(self):
        if self.kind == "active" and self.title is None: raise ValueError("active roadmap item needs a title")
        return self

class Project(Strict):
    id: str = Field(pattern=r"^p\d+$"); mark: str = Field(min_length=1); tag: str = Field(min_length=1)
    badge: Literal["launch", "ship", "bot", "dev"]; cat: Literal["web", "bot", "fun", "tool"]
    wide: bool = False; extra_class: str = Field(default="", pattern=r"^[a-z0-9-]*$"); hidden: bool = False
    chips: list[str] = []; title: I18nText; desc: I18nText; link: Link = Link()
    @field_validator("chips")
    @classmethod
    def _clean_chips(cls, v): return [c.strip() for c in v if c and c.strip()]

class Site(Strict):
    donate_url: str = ""
    @field_validator("donate_url")
    @classmethod
    def _https(cls, v):
        if v and not v.startswith("https://"): raise ValueError("donate_url must start with https://")
        return v

class Content(Strict):
    site: Site = Site(); stats: list[Stat] = Field(min_length=1, max_length=4)
    roadmap: list[RoadmapItem] = []; projects: list[Project] = []
    @model_validator(mode="after")
    def _unique_ids(self):
        for name, items in (("projects", self.projects), ("roadmap", self.roadmap)):
            ids = [i.id for i in items]
            if len(ids) != len(set(ids)): raise ValueError(f"duplicate id in {name}")
        return self

def load_content(path: Path) -> Content:
    return Content.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))

def dumps(content: Content) -> str:
    return json.dumps(content.model_dump(), ensure_ascii=False, indent=2) + "\n"

def save_content(content: Content, path: Path) -> None:
    path = Path(path); tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(dumps(content), encoding="utf-8"); os.replace(tmp, path)

def content_hash(content: Content) -> str:
    canon = json.dumps(content.model_dump(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()

def next_project_id(content: Content) -> str:
    used = [int(p.id[1:]) for p in content.projects]
    return f"p{(max(used) + 1) if used else 1}"
```
`Link` model with an empty url must still serialise `label: {fa:"", en:""}` so `model_dump()` equals the golden JSON — the golden has exactly that shape.

- [ ] **Step 4: Run tests, pass.** — `.venv/bin/pytest tests/test_content.py -v`

- [ ] **Step 5: Commit** — `Add the content schema with atomic save`.

---

### Task 3: Auth primitives — `admin/auth.py`

**Files:** Create `admin/auth.py`, `admin/mkpass.py`, `tests/test_auth.py`.

**Interfaces:**
- Produces: `hash_password(pw: str) -> str`, `verify_password(hash: str, pw: str) -> bool`, `Sessions(secret: str, max_age: int)` with `.issue() -> str` and `.check(token: str | None) -> bool`, `Lockout(limit=5, window=900, clock=time.monotonic)` with `.is_locked(ip) -> bool`, `.record_failure(ip) -> None`, `.reset(ip) -> None`.

- [ ] **Step 1: Failing tests**

```python
# tests/test_auth.py
from admin.auth import hash_password, verify_password, Sessions, Lockout

def test_password_roundtrip():
    h = hash_password("gg-secret"); assert verify_password(h, "gg-secret"); assert not verify_password(h, "nope")

def test_session_token_roundtrip():
    s = Sessions("k", 60); assert s.check(s.issue()); assert not s.check("garbage"); assert not s.check(None)

def test_session_expires():
    s = Sessions("k", -1); assert not s.check(s.issue())

def test_session_secret_bound():
    assert not Sessions("b", 60).check(Sessions("a", 60).issue())

def test_lockout_after_five():
    t = [0.0]; lk = Lockout(limit=5, window=900, clock=lambda: t[0])
    for _ in range(4): lk.record_failure("1.1.1.1")
    assert not lk.is_locked("1.1.1.1")
    lk.record_failure("1.1.1.1"); assert lk.is_locked("1.1.1.1")
    t[0] = 901; assert not lk.is_locked("1.1.1.1")

def test_lockout_reset_on_success():
    lk = Lockout(); [lk.record_failure("x") for _ in range(4)]; lk.reset("x"); [lk.record_failure("x") for _ in range(4)]
    assert not lk.is_locked("x")
```

- [ ] **Step 2: Run, expect ImportError.**

- [ ] **Step 3: Implement**

```python
# admin/auth.py
import time
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError, InvalidHashError
from itsdangerous import TimestampSigner, BadSignature, SignatureExpired

_ph = PasswordHasher()

def hash_password(pw: str) -> str: return _ph.hash(pw)

def verify_password(hash_: str, pw: str) -> bool:
    try: return _ph.verify(hash_, pw)
    except (VerifyMismatchError, VerificationError, InvalidHashError): return False

class Sessions:
    def __init__(self, secret: str, max_age: int):
        self._s = TimestampSigner(secret, salt="gg-admin-session"); self.max_age = max_age
    def issue(self) -> str: return self._s.sign(b"admin").decode()
    def check(self, token) -> bool:
        if not token: return False
        try: return self._s.unsign(token, max_age=self.max_age) == b"admin"
        except (BadSignature, SignatureExpired): return False

class Lockout:
    """5 failures inside the window locks that IP for the window. In-memory: one worker."""
    def __init__(self, limit=5, window=900, clock=time.monotonic):
        self.limit, self.window, self.clock = limit, window, clock
        self._fails: dict[str, int] = {}; self._until: dict[str, float] = {}
    def is_locked(self, ip: str) -> bool:
        until = self._until.get(ip)
        if until is None: return False
        if self.clock() >= until: self._until.pop(ip, None); self._fails.pop(ip, None); return False
        return True
    def record_failure(self, ip: str) -> None:
        n = self._fails.get(ip, 0) + 1; self._fails[ip] = n
        if n >= self.limit: self._until[ip] = self.clock() + self.window; self._fails[ip] = 0
    def reset(self, ip: str) -> None: self._fails.pop(ip, None); self._until.pop(ip, None)
```
`admin/mkpass.py`: `getpass` a password twice, print `hash_password(pw)`.

- [ ] **Step 4: Run tests, pass.**  - [ ] **Step 5: Commit** — `Add password hashing, signed sessions and login lockout`.

---

### Task 4: Publish, backups, restore, git sync — `admin/publish.py` + `admin/config.py`

**Files:** Create `admin/config.py`, `admin/publish.py`, `tests/test_publish.py`.

**Interfaces:**
- Produces: `Settings` dataclass (`repo_dir, live_index, data_dir, password_hash, session_secret, git_sync, session_max_age=43200, backups_keep=20`; properties `content_path, template_path, repo_index, backups_dir, state_path`), `settings_from_env(env) -> Settings`; `publish(s, content, runner=subprocess.run) -> dict`, `list_backups(s) -> list[dict]`, `restore(s, name) -> dict`, `load_state(s) -> dict`, `git_sync(s, message, runner, attempts=3, delay=5.0) -> dict`, `utc_stamp() -> str`.
- Consumes: `build.render`, `admin.content.{Content, load_content, save_content, content_hash}`.

- [ ] **Step 1: Failing tests**

```python
# tests/test_publish.py
import json, shutil, time
from pathlib import Path
from admin.config import Settings
from admin.content import load_content, content_hash
from admin.publish import publish, list_backups, restore, load_state, git_sync

FIX = Path(__file__).parent / "fixtures"

def make_settings(tmp_path, git_sync=False):
    repo = tmp_path / "repo"; repo.mkdir()
    shutil.copy(FIX / "golden-content.json", repo / "content.json")
    shutil.copy(FIX / "golden-template.html", repo / "template.html")
    web = tmp_path / "web"; web.mkdir(); (web / "index.html").write_text("OLD", encoding="utf-8")
    return Settings(repo_dir=repo, live_index=web / "index.html", data_dir=tmp_path / "data",
                    password_hash="x", session_secret="s", git_sync=git_sync, backups_keep=3)

def test_publish_writes_live_and_repo_and_backup(tmp_path):
    s = make_settings(tmp_path); c = load_content(s.content_path)
    r = publish(s, c)
    live = s.live_index.read_text(encoding="utf-8")
    assert "<article" in live and live == s.repo_index.read_text(encoding="utf-8")
    assert not list(s.live_index.parent.glob("*.new"))
    b = s.backups_dir / r["backup"]; assert (b / "index.html").read_text() == "OLD" and (b / "content.json").exists()
    assert load_state(s)["published_hash"] == content_hash(c)

def test_backups_pruned(tmp_path):
    s = make_settings(tmp_path); c = load_content(s.content_path)
    for _ in range(5): publish(s, c); time.sleep(1.05)
    assert len(list_backups(s)) == 3

def test_restore_swaps_both_files(tmp_path):
    s = make_settings(tmp_path); c = load_content(s.content_path)
    first = publish(s, c)
    c.projects[0].mark = "🧪"; from admin.content import save_content; save_content(c, s.content_path)
    time.sleep(1.05); second = publish(s, c)
    r = restore(s, second["backup"])        # that backup holds the state BEFORE the second publish
    assert "🧪" not in s.live_index.read_text(encoding="utf-8")
    assert load_content(s.content_path).projects[0].mark != "🧪"
    assert load_state(s)["published_hash"] == content_hash(load_content(s.content_path))

def test_restore_rejects_bad_name(tmp_path):
    s = make_settings(tmp_path)
    import pytest
    with pytest.raises(ValueError): restore(s, "../etc")

def test_git_sync_retries_then_records(tmp_path):
    s = make_settings(tmp_path); calls = []
    class R:  # fake subprocess.run
        def __init__(self, fails): self.fails = fails
        def __call__(self, cmd, **kw):
            calls.append(cmd)
            if cmd[:2] == ["git", "push"] and self.fails > 0:
                self.fails -= 1; return type("P", (), {"returncode": 1, "stderr": "net", "stdout": ""})()
            return type("P", (), {"returncode": 0, "stderr": "", "stdout": ""})()
    out = git_sync(s, "msg", runner=R(fails=2), attempts=3, delay=0)
    assert out["ok"] and sum(1 for c in calls if c[:2] == ["git", "push"]) == 3
    assert load_state(s)["git_sync"]["ok"]
    out = git_sync(s, "msg", runner=R(fails=5), attempts=3, delay=0)
    assert not out["ok"] and "net" in out["error"]
```

- [ ] **Step 2: Run, expect ImportError.**

- [ ] **Step 3: Implement `admin/config.py`**

```python
import os
from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class Settings:
    repo_dir: Path; live_index: Path; data_dir: Path
    password_hash: str; session_secret: str; git_sync: bool
    session_max_age: int = 12 * 3600; backups_keep: int = 20
    @property
    def content_path(self): return self.repo_dir / "content.json"
    @property
    def template_path(self): return self.repo_dir / "template.html"
    @property
    def repo_index(self): return self.repo_dir / "index.html"
    @property
    def backups_dir(self): return self.data_dir / "backups"
    @property
    def state_path(self): return self.data_dir / "state.json"

def settings_from_env(env=os.environ) -> Settings:
    repo = Path(env.get("GG_REPO_DIR", Path(__file__).resolve().parent.parent))
    return Settings(repo_dir=repo,
                    live_index=Path(env.get("GG_LIVE_INDEX", repo / "data" / "live" / "index.html")),
                    data_dir=Path(env.get("GG_DATA_DIR", repo / "data")),
                    password_hash=env["ADMIN_PASSWORD_HASH"], session_secret=env["SESSION_SECRET"],
                    git_sync=env.get("GG_GIT_SYNC", "1") == "1")
```

- [ ] **Step 4: Implement `admin/publish.py`**

```python
"""Publish = render, back up, atomically replace the live file, then push in the background."""
import json, os, re, shutil, subprocess, threading, time
from datetime import datetime, timezone
from pathlib import Path
from build import render
from admin.config import Settings
from admin.content import Content, load_content, save_content, content_hash

NAME = re.compile(r"^\d{8}T\d{6}Z$")

def utc_stamp() -> str: return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".new"); tmp.write_text(text, encoding="utf-8")
    os.chmod(tmp, 0o644); os.replace(tmp, path)

def load_state(s: Settings) -> dict:
    try: return json.loads(s.state_path.read_text(encoding="utf-8"))
    except FileNotFoundError: return {}

def _update_state(s: Settings, **kw) -> dict:
    st = load_state(s); st.update(kw); s.data_dir.mkdir(parents=True, exist_ok=True)
    _atomic_write(s.state_path, json.dumps(st, ensure_ascii=False, indent=2)); return st

def _snapshot(s: Settings) -> Path:
    """Copy the live index + current content.json into a new backup folder."""
    d = s.backups_dir / utc_stamp(); d.mkdir(parents=True, exist_ok=True)
    if s.live_index.exists(): shutil.copy2(s.live_index, d / "index.html")
    if s.content_path.exists(): shutil.copy2(s.content_path, d / "content.json")
    return d

def _prune(s: Settings) -> None:
    dirs = sorted((p for p in s.backups_dir.iterdir() if p.is_dir() and NAME.match(p.name)), reverse=True)
    for old in dirs[s.backups_keep:]: shutil.rmtree(old)

def list_backups(s: Settings) -> list[dict]:
    if not s.backups_dir.exists(): return []
    out = []
    for p in sorted(s.backups_dir.iterdir(), reverse=True):
        if p.is_dir() and NAME.match(p.name):
            idx = p / "index.html"
            out.append({"name": p.name, "bytes": idx.stat().st_size if idx.exists() else 0, "has_content": (p / "content.json").exists()})
    return out

def publish(s: Settings, content: Content, runner=subprocess.run) -> dict:
    html = render(content.model_dump(), s.template_path)
    backup = _snapshot(s)
    _atomic_write(s.live_index, html); _atomic_write(s.repo_index, html)
    _prune(s)
    st = _update_state(s, last_publish=backup.name, last_publish_bytes=len(html.encode("utf-8")), published_hash=content_hash(content))
    if s.git_sync:
        threading.Thread(target=git_sync, args=(s, f"Publish from admin panel — {backup.name}", runner), daemon=True).start()
    return {"timestamp": backup.name, "backup": backup.name, "bytes": st["last_publish_bytes"]}

def restore(s: Settings, name: str) -> dict:
    if not NAME.match(name or ""): raise ValueError("bad backup name")
    src = s.backups_dir / name
    if not (src / "index.html").exists(): raise FileNotFoundError(name)
    current = _snapshot(s)
    html = (src / "index.html").read_text(encoding="utf-8")
    _atomic_write(s.live_index, html); _atomic_write(s.repo_index, html)
    if (src / "content.json").exists(): save_content(load_content(src / "content.json"), s.content_path)
    _prune(s)
    _update_state(s, last_publish=current.name, last_publish_bytes=len(html.encode("utf-8")),
                  published_hash=content_hash(load_content(s.content_path)), restored_from=name)
    return {"restored": name, "backup": current.name}

def git_sync(s: Settings, message: str, runner=subprocess.run, attempts=3, delay=5.0) -> dict:
    def run(*cmd):
        return runner(list(cmd), cwd=str(s.repo_dir), capture_output=True, text=True)
    err = ""
    run("git", "add", "content.json", "index.html")
    c = run("git", "commit", "-q", "-m", message)   # non-zero when nothing changed: fine
    for i in range(attempts):
        p = run("git", "push", "-q")
        if p.returncode == 0:
            out = {"ok": True, "at": utc_stamp(), "error": ""}; _update_state(s, git_sync=out); return out
        err = (p.stderr or p.stdout or "").strip()[-400:]
        if i + 1 < attempts: time.sleep(delay)
    out = {"ok": False, "at": utc_stamp(), "error": err or "push failed"}; _update_state(s, git_sync=out); return out
```

- [ ] **Step 5: Run tests, pass.**  - [ ] **Step 6: Commit** — `Add publish with backups, restore and background git sync`.

---

### Task 5: The HTTP app — `admin/app.py`, `admin/main.py`

**Files:** Create `admin/app.py`, `admin/main.py`, `tests/test_app.py`. Add a placeholder `admin/static/admin.html` containing `<title>GGmilad Admin</title>` (Task 6 replaces it).

**Interfaces:**
- Produces: `create_app(settings: Settings) -> FastAPI`; routes exactly as the spec table; `admin.main.app` for uvicorn.
- Consumes: everything from Tasks 2–4.

- [ ] **Step 1: Failing tests**

```python
# tests/test_app.py
import json, shutil
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from admin.app import create_app
from admin.auth import hash_password
from admin.config import Settings

FIX = Path(__file__).parent / "fixtures"
H = {"X-Requested-With": "ggmilad-admin"}

@pytest.fixture
def client(tmp_path):
    repo = tmp_path / "repo"; repo.mkdir()
    shutil.copy(FIX / "golden-content.json", repo / "content.json"); shutil.copy(FIX / "golden-template.html", repo / "template.html")
    (repo / "admin" / "static").mkdir(parents=True); (repo / "admin" / "static" / "admin.html").write_text("<title>GGmilad Admin</title>")
    s = Settings(repo_dir=repo, live_index=tmp_path / "web" / "index.html", data_dir=tmp_path / "data",
                 password_hash=hash_password("pw"), session_secret="s", git_sync=False)
    return TestClient(create_app(s), base_url="https://testserver")

def login(c): r = c.post("/admin/api/login", json={"password": "pw"}, headers=H); assert r.status_code == 204; return c

def test_ui_served_without_auth(client):
    assert client.get("/admin/").status_code == 200 and "GGmilad Admin" in client.get("/admin/").text

def test_api_requires_session(client):
    assert client.get("/admin/api/content").status_code == 401
    assert client.get("/admin/preview").status_code == 401

def test_wrong_password_401_and_lockout(client):
    for _ in range(5): assert client.post("/admin/api/login", json={"password": "x"}, headers=H).status_code == 401
    assert client.post("/admin/api/login", json={"password": "pw"}, headers=H).status_code == 429

def test_login_sets_cookie_and_content_readable(client):
    login(client); r = client.get("/admin/api/content"); assert r.status_code == 200 and r.json()["projects"][0]["id"] == "p1"

def test_mutation_requires_header(client):
    login(client); body = client.get("/admin/api/content").json()
    assert client.put("/admin/api/content", json=body).status_code == 403
    assert client.put("/admin/api/content", json=body, headers=H).status_code == 200

def test_put_validates_and_persists(client):
    login(client); body = client.get("/admin/api/content").json()
    body["projects"][0]["title"]["en"] = ""; assert client.put("/admin/api/content", json=body, headers=H).status_code == 422
    body["projects"][0]["title"]["en"] = "Changed"; r = client.put("/admin/api/content", json=body, headers=H)
    assert r.status_code == 200 and r.json()["content"]["projects"][0]["title"]["en"] == "Changed" and r.json()["dirty"] is True

def test_preview_and_publish_and_status(client):
    login(client)
    assert "<article" in client.get("/admin/preview").text
    r = client.post("/admin/api/publish", headers=H); assert r.status_code == 200 and r.json()["bytes"] > 1000
    st = client.get("/admin/api/status").json(); assert st["dirty"] is False and st["last_publish"]

def test_backups_and_restore(client):
    login(client); client.post("/admin/api/publish", headers=H)
    body = client.get("/admin/api/content").json(); body["projects"][0]["mark"] = "🧪"
    client.put("/admin/api/content", json=body, headers=H); import time; time.sleep(1.05)
    client.post("/admin/api/publish", headers=H)
    names = [b["name"] for b in client.get("/admin/api/backups").json()]; assert len(names) == 2
    assert client.post("/admin/api/restore", json={"name": names[0]}, headers=H).status_code == 200
    assert client.get("/admin/api/content").json()["projects"][0]["mark"] != "🧪"
    assert client.post("/admin/api/restore", json={"name": "../x"}, headers=H).status_code == 422

def test_logout(client):
    login(client); client.post("/admin/api/logout", headers=H); assert client.get("/admin/api/content").status_code == 401
```

- [ ] **Step 2: Run, expect ImportError.**

- [ ] **Step 3: Implement `admin/app.py`**

```python
from pathlib import Path
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, ValidationError
from build import render
from admin.auth import Lockout, Sessions, verify_password
from admin.config import Settings
from admin.content import Content, content_hash, load_content, next_project_id, save_content
from admin.publish import list_backups, load_state, publish, restore

COOKIE = "gg_admin"; HEADER = "x-requested-with"; HEADER_VALUE = "ggmilad-admin"
STATIC = Path(__file__).parent / "static"

class LoginBody(BaseModel): password: str
class RestoreBody(BaseModel): name: str

def create_app(s: Settings) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    sessions = Sessions(s.session_secret, s.session_max_age); lockout = Lockout()
    static_dir = (s.repo_dir / "admin" / "static") if (s.repo_dir / "admin" / "static" / "admin.html").exists() else STATIC

    def ip(req: Request) -> str: return req.headers.get("x-real-ip") or (req.client.host if req.client else "?")
    def require_session(req: Request):
        if not sessions.check(req.cookies.get(COOKIE)): raise HTTPException(401, "not signed in")
    def require_header(req: Request):
        if req.headers.get(HEADER) != HEADER_VALUE: raise HTTPException(403, "missing X-Requested-With")
    def current() -> Content: return load_content(s.content_path)
    def dirty(c: Content) -> bool: return load_state(s).get("published_hash") != content_hash(c)

    @app.get("/admin")
    def root_redirect(): return RedirectResponse("/admin/", status_code=301)
    @app.get("/admin/", response_class=HTMLResponse)
    def ui(): return FileResponse(static_dir / "admin.html", media_type="text/html")

    @app.post("/admin/api/login", status_code=204, dependencies=[Depends(require_header)])
    def login(body: LoginBody, req: Request, resp: Response):
        client = ip(req)
        if lockout.is_locked(client): raise HTTPException(429, "locked; try again in 15 minutes")
        if not verify_password(s.password_hash, body.password):
            lockout.record_failure(client); raise HTTPException(401, "wrong password")
        lockout.reset(client)
        resp.set_cookie(COOKIE, sessions.issue(), max_age=s.session_max_age, path="/admin", httponly=True, secure=True, samesite="strict")
        return Response(status_code=204)

    @app.post("/admin/api/logout", status_code=204, dependencies=[Depends(require_session), Depends(require_header)])
    def logout(resp: Response):
        resp.delete_cookie(COOKIE, path="/admin"); return Response(status_code=204, headers=resp.headers)

    @app.get("/admin/api/content", dependencies=[Depends(require_session)])
    def get_content():
        c = current(); return {"content": c.model_dump(), "dirty": dirty(c), "next_project_id": next_project_id(c)}

    @app.put("/admin/api/content", dependencies=[Depends(require_session), Depends(require_header)])
    def put_content(body: dict):
        try: c = Content.model_validate(body)
        except ValidationError as e: return JSONResponse({"detail": e.errors(include_url=False)}, status_code=422)
        save_content(c, s.content_path)
        return {"content": c.model_dump(), "dirty": dirty(c), "next_project_id": next_project_id(c)}

    @app.get("/admin/preview", response_class=HTMLResponse, dependencies=[Depends(require_session)])
    def preview(): return HTMLResponse(render(current().model_dump(), s.template_path))

    @app.post("/admin/api/publish", dependencies=[Depends(require_session), Depends(require_header)])
    def do_publish(): r = publish(s, current()); r["state"] = load_state(s); return r

    @app.get("/admin/api/backups", dependencies=[Depends(require_session)])
    def backups(): return list_backups(s)

    @app.post("/admin/api/restore", dependencies=[Depends(require_session), Depends(require_header)])
    def do_restore(body: RestoreBody):
        try: r = restore(s, body.name)
        except ValueError: raise HTTPException(422, "bad backup name")
        except FileNotFoundError: raise HTTPException(404, "no such backup")
        r["state"] = load_state(s); return r

    @app.get("/admin/api/status", dependencies=[Depends(require_session)])
    def status():
        st = load_state(s); c = current()
        return {"last_publish": st.get("last_publish"), "last_publish_bytes": st.get("last_publish_bytes"),
                "git_sync": st.get("git_sync"), "restored_from": st.get("restored_from"), "dirty": dirty(c),
                "live_bytes": s.live_index.stat().st_size if s.live_index.exists() else 0}
    return app
```
`admin/main.py`: `from admin.app import create_app; from admin.config import settings_from_env; app = create_app(settings_from_env())`.
Note on the login route: FastAPI's `Response` parameter + returning a new `Response` — set the cookie on the returned response instead; test drives the exact shape.

- [ ] **Step 4: Run tests, pass.**  - [ ] **Step 5: Commit** — `Add the admin HTTP app`.

---

### Task 6: The panel UI — `admin/static/admin.html`

**Files:** Replace `admin/static/admin.html`.

**Interfaces:** Consumes the API from Task 5 exactly; sends `X-Requested-With: ggmilad-admin` on every POST/PUT; treats any 401 as "show the login view".

Requirements (design pass with the frontend-design skill at execution time):
- One self-contained file; `dir="rtl"`, `lang="fa"`; Google Fonts `Lalezar` (display), `Vazirmatn` (body), `JetBrains Mono` (labels/data) — the portfolio's own faces; dark ground in the portfolio's palette (read the tokens from `template.html` `:root`).
- Views: **login** (one password field, error line, lockout message on 429); **app** with a top bar (`GGMILAD // ADMIN`, status pill: «منتشرشده» / «تغییرات منتشرنشده», git-sync dot with tooltip, buttons «پیش‌نمایش» (opens `/admin/preview` in a new tab) and «انتشار»), tabs «پروژه‌ها» / «لِوِل‌ها» / «سایت», a «پشتیبان‌ها» drawer listing backups with «بازگردانی» (confirm dialog).
- Projects tab: list rows (drag handle, mark, fa title, badge chip, cat chip, hidden eye toggle, ▲▼ buttons as the non-drag fallback). Row click expands an inline form: mark, tag, badge select, cat select, wide, hidden, extra_class, chips (comma-separated, `,` or `،`), link url + link label fa/en, title fa/en, desc fa/en (textareas; fa fields `dir="rtl"`, en fields `dir="ltr"`). «افزودن پروژه» prepends a blank project with `next_project_id`. «حذف» with confirm.
- Roadmap tab: same pattern; kind select toggles title/progress fields.
- Site tab: the stats rows (value, suffix, count toggle, label fa/en) and `donate_url`.
- **Save model:** one in-memory `content` object; every form change marks it; a sticky «ذخیره» button PUTs the whole object; server validation errors are shown next to the offending field (map `loc` → field). After save, `dirty` from the response drives the status pill. Publish → POST, then GET status; show bytes and time. Unsaved changes warn on `beforeunload`.
- Keyboard: Ctrl/Cmd+S saves. Reduced motion respected. Everything works at 375 px wide.

- [ ] **Step 1: Build it.**  - [ ] **Step 2: Manual test:** run `GG_REPO_DIR=$PWD GG_LIVE_INDEX=/tmp/ggweb/index.html GG_DATA_DIR=/tmp/ggdata ADMIN_PASSWORD_HASH=... SESSION_SECRET=dev GG_GIT_SYNC=0 .venv/bin/uvicorn admin.main:app --port 9914`, open `http://127.0.0.1:9914/admin/` — note `Secure` cookies need HTTPS or `localhost`; use `http://localhost:9914/admin/` (browsers treat localhost as secure). Log in, edit a project, save, preview, publish into `/tmp/ggweb`, restore.  - [ ] **Step 3: Commit** — `Add the admin panel UI`.

---

### Task 7: Deployment files, docs, spec touch-up

**Files:** Create `deploy/ggmilad-admin.service`, `deploy/nginx-admin.location`, `deploy/setup.sh`, `deploy/README.md`; modify `README.md`; modify the spec (card visibility is `hidden`, nav is `site.donate_url`).

- `ggmilad-admin.service`: copy of `tgdup.service` shape — `User=ggadmin`, `WorkingDirectory=/opt/ggmilad-admin`, `EnvironmentFile=/opt/ggmilad-admin/.env`, `ExecStart=/opt/ggmilad-admin/.venv/bin/uvicorn admin.main:app --host 127.0.0.1 --port 9914 --workers 1 --proxy-headers --forwarded-allow-ips 127.0.0.1`, `Environment=GG_REPO_DIR=/opt/ggmilad-admin GG_LIVE_INDEX=/var/www/ggmilad/index.html GG_DATA_DIR=/opt/ggmilad-admin/data`, hardening block, `ReadWritePaths=/opt/ggmilad-admin /var/www/ggmilad`, `ProtectHome=read-only` (git's key lives in `/var/lib/ggadmin/.ssh`, which is not under /home).
- `nginx-admin.location`: the two `location` blocks from the spec plus `proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;` and `proxy_read_timeout 60s;`.
- `setup.sh` (root, idempotent): phase `key` → create user `ggadmin` (home `/var/lib/ggadmin`), ssh keygen, print pubkey, `ssh-keyscan github.com`; phase `install` → clone via `git@github.com:miladdhq/ggmilad-portfolio.git` into `/opt/ggmilad-admin` (or `git pull`), venv + `pip install -r requirements.txt`, `git config user.name "GGmilad Admin"`, `git config user.email "admin@ggon.top"`, `chown -R ggadmin:www-data /var/www/ggmilad && chmod 775 /var/www/ggmilad && chmod 664 /var/www/ggmilad/index.html`, install the unit, insert the location snippet into `/etc/nginx/sites-available/ggmilad` right before the line `    location / {` in the 443 block if `location /admin/` is absent, `nginx -t && systemctl reload nginx`, `systemctl enable --now ggmilad-admin`.
- README: new "Editing content" section: the panel, `content.json` vs `template.html`, the rule of truth, local `python build.py`.

- [ ] **Step 1: Write the files.**  - [ ] **Step 2: `bash -n deploy/setup.sh`; `systemd-analyze verify deploy/ggmilad-admin.service` if available.**  - [ ] **Step 3: Commit** — `Add deployment files and document the content workflow`. Then `git push` (this also pushes the held-back donate commit; the template gates it).

---

### Task 8: Deploy to the VPS and first publish

- [ ] **Step 1:** `scp deploy/setup.sh pishi-vps:/root/` · `ssh pishi-vps bash /root/setup.sh key` → copy the printed public key · `gh repo deploy-key add <keyfile> -R miladdhq/ggmilad-portfolio --title "ggmilad-admin VPS" --allow-write`.
- [ ] **Step 2:** on the VPS `sudo -u ggadmin ssh -T git@github.com` must say "successfully authenticated". Then `bash /root/setup.sh install`.
- [ ] **Step 3:** create `.env` on the VPS: `ADMIN_PASSWORD_HASH` from `mkpass.py` (password chosen by Milad, entered on the server, never in chat), `SESSION_SECRET=$(openssl rand -hex 32)`, `GG_GIT_SYNC=1`; `chmod 600`, owner ggadmin. `systemctl restart ggmilad-admin`; `journalctl -u ggmilad-admin -n 20`.
- [ ] **Step 4:** before the first publish, set the initial content on the server: `p23.hidden = true`, `site.donate_url = ""` (edit via the panel, or `python - <<...>>` on the server), so the dead donate link stays off.
- [ ] **Step 5:** `curl -sI https://ggon.top/admin/` → 200; log in from a browser; Publish; `curl -s https://ggon.top | md5sum` equals `md5sum /var/www/ggmilad/index.html`; the page has no `donate.ggon.top` and no `چای`; `git log -1` on the server shows the panel's commit and `gh api repos/miladdhq/ggmilad-portfolio/commits?per_page=1` shows it pushed.
- [ ] **Step 6:** `git pull` locally so the working copy matches; update the memory note `ggmilad-portfolio-deployment.md` (deploy is now Publish-from-panel; scp only for template changes) and add `ggmilad-admin-panel.md`.

---

## Self-review

- **Spec coverage:** content model → T1/T2; template+build+golden → T1; routes/auth/CSRF → T3/T5; publish/backup/restore/git → T4; UI → T6; server layout/nginx/systemd/rule of truth → T7/T8; rollout incl. donate gating → T8. The spec's "donate_url empty → card omitted" is corrected to "card visibility is `hidden`" in T7.
- **Placeholders:** the UI task describes rather than lists code; it is executed in-session with the design skill and tested manually — accepted.
- **Type consistency:** `publish()` returns `{timestamp, backup, bytes}`; `restore()` returns `{restored, backup}`; `load_state()` keys `last_publish, last_publish_bytes, published_hash, git_sync{ok,at,error}, restored_from`; `Settings` properties as listed; `Content.model_dump()` equals the JSON on disk — used by T1's render and T5's API.
