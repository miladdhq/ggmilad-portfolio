# GGmilad — Portfolio

<div align="right">

**پورتفولیوی شخصی GGmilad** — یک فایل HTML خودبسنده، دوزبانه (فارسی/انگلیسی)، با تم دارک و RTL کامل.

</div>

A personal portfolio site served as **one self-contained HTML file** — all CSS,
JavaScript, and content inlined. No dependencies, no backend on the public site.

The content that changes over time (project cards, roadmap levels, hero stats)
lives in `content.json`; the design lives in `template.html`; `build.py` joins
them into `index.html`. A small admin panel at `/admin` edits the JSON and
publishes the result — see **Editing content** below.

**Live:** <https://ggon.top>

---

## What's inside · چه چیزی داخلش است

| Section | |
|---|---|
| `01 // ABOUT` | Who I am and what I build |
| `02 // QUESTS_COMPLETED` | Ten projects — stores, bots, games, an offline life-OS |
| `03 // INVENTORY` | The stack I work with |
| `04 // NEXT_LEVELS` | What's in progress and what's still locked |
| `05 // CONTACT` | Telegram and email |

The whole thing is framed as a game UI — quests, inventory, levels, XP — because
a portfolio that looks like every other portfolio doesn't get remembered.

## Details worth knowing · نکته‌های فنی

- **Fully bilingual.** Every string lives in an `I18N` dictionary with `fa` and
  `en` sides, applied through `data-i18n` attributes. Switching language also
  flips `dir` between `rtl` and `ltr` and swaps the whole layout.
- **RTL-first.** Persian is the default language; English is the translation,
  not the other way round.
- **No framework.** Vanilla JS, hand-written CSS, CSS custom properties for
  theming. The only reason it's one file is that it genuinely fits in one.
- **Respects `prefers-reduced-motion`** — the starfield, scroll reveals, and
  the typing effect all stand down when the visitor asks for less motion.
- **Project filtering** by category (web / bots / playground) with no page
  reloads.

## Stack

`HTML` · `CSS` · `Vanilla JavaScript` — that's the entire list.

## Structure

```
index.html        the site, as served — the build output, committed
content.json      the data: projects, roadmap, hero stats, donate URL
template.html     the design: everything else, with Jinja loops for the three regions
build.py          render(content, template) → index.html   (python build.py > index.html)
admin/            the panel: FastAPI app + single-file UI
deploy/           systemd unit, nginx location, server setup script
tools/migrate.py  the one-time split that produced content.json + template.html
tests/            golden round-trip, schema, auth, publish, HTTP
```

## Editing content · ویرایش محتوا

**Content** — project cards, roadmap levels, hero stats, the donate URL — is
edited in the panel at `https://ggon.top/admin`. Save writes `content.json`;
Publish renders the site, backs up the previous version, replaces the live
file atomically, and commits + pushes to this repo in the background. Restore
brings back any of the last twenty publishes, content and site together.

**Design** — layout, CSS, JS, the sections that rarely change — is edited in
`template.html` here, then: commit, push, `git pull` on the server, Publish.

The rule that keeps the two from fighting: never edit `content.json` in two
places. The server's copy is the truth after launch; git follows it.

To rebuild by hand (for a local check, or without the panel):

```bash
python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python build.py > index.html
.venv/bin/pytest
```

`tests/test_golden.py` proves the split is lossless: rendering the migrated
content reproduces the original `index.html`, markup and both language
dictionaries.

## Deploying · استقرار

The public site is still a static file: nginx serves `/var/www/ggmilad/index.html`.
The panel writes that file on Publish. First-time server setup is
`deploy/setup.sh` (`key`, then `install`); the panel runs as the `ggadmin`
system user on `127.0.0.1:9914` and nginx proxies only `/admin/` to it.

Without the panel, deployment is still just a copy:

```bash
scp index.html <user>@<host>:/var/www/ggmilad/index.html
```

Behind nginx it wants `Cache-Control: no-cache` — the entire site is this single
file, so a long cache would strand visitors on a stale build while the ETag
still gives you cheap `304`s.

---

<div align="right">

ساخته‌شده با ☕ و کمی آشوب.

</div>
