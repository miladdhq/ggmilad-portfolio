# GGmilad — Portfolio

<div align="right">

**پورتفولیوی شخصی GGmilad** — یک فایل HTML خودبسنده، دوزبانه (فارسی/انگلیسی)، با تم دارک و RTL کامل.

</div>

A personal portfolio site built as **one self-contained HTML file** — all CSS,
JavaScript, and content inlined. No build step, no dependencies, no backend.

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
index.html    the site — everything lives here
README.md     this file
```

## Deploying · استقرار

It's a static file, so deployment is a copy. Serve it as `index.html` from any
web server:

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
