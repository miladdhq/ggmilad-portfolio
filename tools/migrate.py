"""One-time split of index.html into content.json + template.html.

    python tools/migrate.py index.html

Line-based on purpose: the three editable regions each open on a known
line and close on the next line that is exactly two-space-indented
`</div>`, and the I18N dictionaries sit between `  var I18N={` and `  };`.
Anything the regexes cannot account for is an error, not a silent drop.
"""
import json
import re
import sys
from pathlib import Path

STR = r"""'(?P<k>[^']+)':(?P<v>'(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*")"""

_WS = r"\s*"
ARTICLE = re.compile(
    r'<article class="card(?P<cls>[^"]*)" data-cat="(?P<cat>[a-z]+)">' + _WS
    + r'<div class="card-mark">(?P<mark>.*?)</div>' + _WS
    + r'<div class="card-top"><span class="card-tag">(?P<tag>.*?)</span>'
    + r'<span class="badge badge-(?P<badge>[a-z]+)" data-i18n="badge\.[a-z]+">.*?</span></div>' + _WS
    + r'<h3 data-i18n="(?P<id>p\d+)\.t">(?P<title>.*?)</h3>' + _WS
    + r'<p data-i18n="(?P=id)\.d">(?P<desc>.*?)</p>' + _WS
    + r'<div class="chips">(?P<chips>.*?)</div>' + _WS
    + r'(?:<a class="card-link" href="(?P<url>[^"]*)"[^>]*><span data-i18n="(?P=id)\.cta">(?P<cta>.*?)</span>'
    + r'<span class="ltr">↗</span></a>' + _WS + r')?'
    + r'</article>',
    re.S,
)
STAT = re.compile(
    r'<div class="hstat"><b class="mono"(?: data-count="(?P<count>\d+)" data-suffix="(?P<suffix>[^"]*)")?>'
    r'(?P<text>.*?)</b><span data-i18n="hero\.stat\d">(?P<label>.*?)</span></div>'
)
ACTIVE = re.compile(
    r'<div class="level level-active reveal">\s*<span class="level-tag">(?P<tag>.*?)</span>\s*'
    r'<h3 data-i18n="road\.t(?P<n>\d)">(?P<title>.*?)</h3>\s*<p data-i18n="road\.d\d">(?P<body>.*?)</p>\s*'
    r'<div class="progress">\s*<div class="progress-info"><span>(?P<plabel>.*?)</span><span>(?P<pct>\d+)%</span></div>'
    r'.*?</div>\s*</div>\s*</div>',
    re.S,
)
LOCKED = re.compile(
    r'<div class="level level-locked reveal">\s*<span class="lock">🔒</span>\s*'
    r'<span class="level-tag">(?P<tag>.*?)</span>\s*<h3 data-i18n="road\.locked">.*?</h3>\s*'
    r'<p class="hint" data-i18n="road\.d(?P<n>\d)">(?P<body>.*?)</p>\s*</div>',
    re.S,
)
# dictionary lines the template generates instead of keeping literally
GEN_KEY = re.compile(r"\s*'(p\d+\.(t|d|cta)|road\.[td]\d|hero\.stat\d)':")

OPEN_STATS = '  <div class="hero-stats fadeup d7">'
OPEN_PROJECTS = '  <div class="projects-grid" id="projectsGrid">'
OPEN_ROADMAP = '  <div class="roadmap-grid">'


def _unescape(m):
    if m.group(1) == "u":
        return chr(int(m.group(2), 16))
    return {"n": "\n", "t": "\t"}.get(m.group(3), m.group(3))


def js_decode(lit: str) -> str:
    return re.sub(r"\\(u)([0-9a-fA-F]{4})|\\(.)", _unescape, lit[1:-1])


def region(lines, opener):
    start = lines.index(opener)
    end = next(i for i in range(start + 1, len(lines)) if lines[i] == "  </div>")
    return start, end  # lines[start+1:end] is the body


def dict_bounds(lines):
    a = lines.index("  var I18N={")
    b = lines.index("  };", a)
    e = lines.index("    en:{", a)
    return a, e, b


def i18n_dicts(lines):
    a, e, b = dict_bounds(lines)
    fa = "\n".join(lines[a:e])
    en = "\n".join(lines[e:b])
    return (
        {m.group("k"): js_decode(m.group("v")) for m in re.finditer(STR, fa)},
        {m.group("k"): js_decode(m.group("v")) for m in re.finditer(STR, en)},
    )


def extract(html: str) -> dict:
    lines = html.split("\n")
    fa, en = i18n_dicts(lines)

    def t(key):
        return {"fa": fa[key], "en": en[key]}

    s0, s1 = region(lines, OPEN_STATS)
    stats = []
    for m in STAT.finditer("\n".join(lines[s0 + 1 : s1])):
        n = len(stats) + 1
        if m.group("count"):
            stats.append({"value": m.group("count"), "suffix": m.group("suffix"), "count": True, "label": t(f"hero.stat{n}")})
        else:
            stats.append({"value": m.group("text"), "suffix": "", "count": False, "label": t(f"hero.stat{n}")})

    p0, p1 = region(lines, OPEN_PROJECTS)
    body = "\n".join(lines[p0 + 1 : p1])
    projects = []
    for m in ARTICLE.finditer(body):
        cls = m.group("cls").split()
        extra = [c for c in cls if c not in ("wide", "reveal")]
        pid = m.group("id")
        has_link = bool(m.group("url"))
        projects.append({
            "id": pid,
            "mark": m.group("mark"),
            "tag": m.group("tag"),
            "badge": m.group("badge"),
            "cat": m.group("cat"),
            "wide": "wide" in cls,
            "extra_class": extra[0] if extra else "",
            "hidden": False,
            "chips": re.findall(r'<span class="chip">(.*?)</span>', m.group("chips")),
            "title": t(f"{pid}.t"),
            "desc": t(f"{pid}.d"),
            "link": {"url": m.group("url") or "", "label": t(f"{pid}.cta") if has_link else {"fa": "", "en": ""}},
        })
    if len(projects) != body.count("<article"):
        raise SystemExit(f"unparsed article in projects grid: {len(projects)} of {body.count('<article')}")

    r0, r1 = region(lines, OPEN_ROADMAP)
    rb = "\n".join(lines[r0 + 1 : r1])
    roadmap = []
    matches = sorted(list(ACTIVE.finditer(rb)) + list(LOCKED.finditer(rb)), key=lambda m: m.start())
    for m in matches:
        n = m.group("n")
        if "level-active" in m.group(0):
            roadmap.append({
                "id": f"r{n}", "kind": "active", "tag": m.group("tag"),
                "title": t(f"road.t{n}"), "body": t(f"road.d{n}"),
                "progress": {"label": m.group("plabel"), "percent": int(m.group("pct"))},
            })
        else:
            roadmap.append({
                "id": f"r{n}", "kind": "locked", "tag": m.group("tag"),
                "title": None, "body": t(f"road.d{n}"), "progress": None,
            })
    if len(roadmap) != rb.count('<div class="level '):
        raise SystemExit("unparsed level in roadmap grid")

    donate = re.search(r'href="(https://donate\.ggon\.top)"', html)
    return {
        "site": {"donate_url": donate.group(1) if donate else ""},
        "stats": stats,
        "roadmap": roadmap,
        "projects": projects,
    }


STATS_TPL = (
    '{% for s in stats %}    <div class="hstat"><b class="mono"{% if s.count %} data-count="{{ s.value }}" '
    'data-suffix="{{ s.suffix }}"{% endif %}>{{ s.value }}{{ s.suffix }}</b>'
    '<span data-i18n="hero.stat{{ loop.index }}">{{ s.label.fa }}</span></div>\n'
    '{% endfor %}'
)

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
    if "{{" in html or "{%" in html:
        raise SystemExit("index.html already contains Jinja delimiters")
    lines = html.split("\n")
    # Replace the three regions, last one first so earlier line numbers stay valid.
    for opener, tpl in ((OPEN_ROADMAP, ROADMAP_TPL), (OPEN_PROJECTS, PROJECTS_TPL), (OPEN_STATS, STATS_TPL)):
        a, b = region(lines, opener)
        lines[a + 1 : b] = [tpl.rstrip("\n")]
    # Swap the generated dictionary lines for one marker per language.
    a, e, b = dict_bounds(lines)
    out, placed = [], {"fa": False, "en": False}
    for i, ln in enumerate(lines):
        if a < i < b and GEN_KEY.match(ln):
            lang = "fa" if i < e else "en"
            if not placed[lang]:
                out.append("{{ i18n_" + lang + "|safe }}")
                placed[lang] = True
            continue
        out.append(ln)
    lines = out
    # The nav's donate anchors only render when a donate URL is set.
    for i, ln in enumerate(lines):
        if 'href="https://donate.ggon.top"' in ln and "card-link" not in ln:
            lines[i] = (
                "{% if site.donate_url %}"
                + ln.replace('href="https://donate.ggon.top"', 'href="{{ site.donate_url }}"')
                + "{% endif %}"
            )
    return "\n".join(lines)


if __name__ == "__main__":
    src = Path(sys.argv[1] if len(sys.argv) > 1 else "index.html")
    html = src.read_text(encoding="utf-8")
    Path("content.json").write_text(json.dumps(extract(html), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    Path("template.html").write_text(make_template(html), encoding="utf-8")
    print("wrote content.json and template.html")
