"""The split must be lossless: content.json + template.html rendered back
must equal the index.html they were extracted from."""
import json
import re
from pathlib import Path

from build import render
from tools.migrate import extract, make_template

FIX = Path(__file__).parent / "fixtures"
GOLD = (FIX / "golden-index.html").read_text(encoding="utf-8")

# 'key':'value'  or  'key':"value"  — the shapes the I18N dictionaries use
STR = r"""'(?P<k>[^']+)':(?P<v>'(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*")"""


def _unescape(m):
    if m.group(1) == "u":
        return chr(int(m.group(2), 16))
    return {"n": "\n", "t": "\t"}.get(m.group(3), m.group(3))


def _js_decode(lit: str) -> str:
    return re.sub(r"\\(u)([0-9a-fA-F]{4})|\\(.)", _unescape, lit[1:-1])


def _dict_span(html: str):
    start = html.index("var I18N={")
    end = html.index("\n  };", start)
    return start, end


def i18n(html: str) -> dict:
    start, end = _dict_span(html)
    block = html[start:end]
    fa_i, en_i = block.index("fa:{"), block.index("en:{")
    return {
        lang: {m.group("k"): _js_decode(m.group("v")) for m in re.finditer(STR, seg)}
        for lang, seg in (("fa", block[fa_i:en_i]), ("en", block[en_i:]))
    }


def markup(html: str) -> str:
    start, end = _dict_span(html)
    html = html[:start] + "I18N" + html[end:]
    html = re.sub(r"\s+", " ", html)
    # The original has a few bare "&" in text; autoescape serialises them as
    # "&amp;", which renders identically. Compare the decoded form.
    html = html.replace("&amp;", "&")
    return re.sub(r">\s+<", "><", html).strip()


def _render_from_golden() -> str:
    content = extract(GOLD)
    tpl = FIX / "golden-template.html"
    tpl.write_text(make_template(GOLD), encoding="utf-8")
    return render(content, tpl)


def test_render_reproduces_golden_markup():
    assert markup(_render_from_golden()) == markup(GOLD)


def test_render_reproduces_golden_i18n():
    assert i18n(_render_from_golden()) == i18n(GOLD)


def test_committed_split_matches_migration():
    committed = json.loads((FIX / "golden-content.json").read_text(encoding="utf-8"))
    assert committed == extract(GOLD)
    assert (FIX / "golden-template.html").read_text(encoding="utf-8") == make_template(GOLD)
