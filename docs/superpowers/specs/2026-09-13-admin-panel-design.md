# Admin panel for ggon.top — design

**Date:** 2026-09-13 · **Status:** approved in conversation, implementing

## Why

The portfolio is one 112 KB `index.html`. Every project card exists three
times in it: as Persian markup, as a `p*.t` / `p*.d` pair in `I18N.fa`, and
again in `I18N.en`. Adding a project means editing three places by hand,
committing, and `scp`-ing the file up. Same for the roadmap and the hero
stats — the only three things on the site that actually change over time.

The panel removes that. Content moves into a JSON file; the design stays
in a template; a small app on the VPS lets Milad edit the JSON from any
device and publish the static site with one button. **The public site
stays exactly what it is: one static file served by nginx with no runtime
dependency.** If the panel is down, ggon.top does not notice.

## Non-goals

- No image uploads; cards keep their emoji marks.
- No change to the site's look. About, skills, contact, CSS and JS stay
  literal in the template and are still edited by hand.
- No multi-user, no roles. One password, one person.
- No server-side rendering of the public site.

## Decisions taken

| Decision | Choice | Why |
|---|---|---|
| Scope | projects + roadmap + hero stats (+ donate URL) | the parts that change |
| Where | VPS, at `https://ggon.top/admin` | edit from phone; no new DNS or cert needed |
| Site production | regenerate the static file on Publish | keeps the single-file site |
| Stack | Python 3.12, FastAPI, Jinja2, pydantic; single-file admin UI | matches the other apps on that VPS |
| Storage | `content.json` in the repo working copy | 23 records; diffable; committed |
| Git | server commits + pushes after each publish, background, retried | repo stays current without manual work |

## Content model — `content.json`

```json
{
  "site":     { "donate_url": "" },
  "stats":    [ { "value": "22", "suffix": "+", "count": true,
                  "label": { "fa": "پروژه تحویل‌شده", "en": "projects shipped" } } ],
  "roadmap":  [ { "id": "r1", "kind": "active", "tag": "▶ IN_PROGRESS",
                  "title": { "fa": "…", "en": "…" }, "body": { "fa": "…", "en": "…" },
                  "progress": { "label": "DEPLOY", "percent": 85 } },
                { "id": "r2", "kind": "locked", "tag": "LOCKED — LV.2",
                  "body": { "fa": "…", "en": "…" } } ],
  "projects": [ { "id": "p1", "mark": "🛒", "tag": "E-COMMERCE / FLAGSHIP",
                  "badge": "launch", "cat": "web", "wide": true, "hidden": false,
                  "chips": ["Next.js", "TypeScript"],
                  "title": { "fa": "…", "en": "…" }, "desc": { "fa": "…", "en": "…" },
                  "link": { "url": "", "label": { "fa": "", "en": "" } } } ]
}
```

- Array order is display order. The panel reorders by drag.
- `id` is stable and never reused; it becomes the `data-i18n` key prefix
  (`p1.t`, `p1.d`, `r1.t`, `r1.d`). New projects get the next free `pN`.
- `badge` ∈ `launch | ship | bot | dev` — the four `badge.*` i18n keys.
- `cat` ∈ `web | bot | fun | tool` — the four filter buttons.
- `hidden: true` keeps the record but renders nothing.
- `link.url` empty → no card link. Non-empty → the `.card-link` anchor with
  the per-language label (this is what the donate card uses today).
- `site.donate_url` empty → the nav "حمایت" link and the donate card are
  both omitted. This is how the held-back donate work stays off the live
  site until `donate.ggon.top` has an A record.
- `stats[].count: true` emits `data-count`/`data-suffix` so the counter
  animation runs; `false` prints the value literally (the `∞`).
- Locked roadmap items have no title: the template prints `road.locked`.

Validation (pydantic): non-empty `fa` and `en` for every title/desc/label,
enum checks on `badge`/`cat`/`kind`, `percent` 0–100, unique ids, URLs
must be `https://`.

## Template and build

`template.html` is today's `index.html` with three regions replaced by
Jinja loops — the `#projectsGrid` articles, the `.roadmap-grid` levels and
the `.hero-stats` blocks — plus the generated `p*`/`r*` entries inside both
`I18N` dictionaries and the two donate nav anchors. Everything else is
literal.

`build.py` exposes `render(content: dict, template_path) -> str` and a CLI
(`python build.py content.json template.html > index.html`). Autoescaping
is on; the i18n values are emitted through a `js_string` filter so quotes,
newlines and `</script>` cannot break the script block.

**Golden test.** `migrate.py` extracts the 23 cards, 3 roadmap items and 3
stats from the committed `index.html` into `content.json` once. The test
renders that JSON with `donate_url` set and p23 visible and asserts the
output equals the committed `index.html` after whitespace normalisation.
That is the proof nothing was lost; it must pass before the app is built.

## The admin app — `admin/`

FastAPI, mounted under `root_path="/admin"`, uvicorn on `127.0.0.1:9914`,
one worker.

| Route | Auth | Does |
|---|---|---|
| `GET  /admin/` | – | login page, or the app if the session cookie is valid |
| `POST /admin/api/login` | – | `{password}` → sets session cookie; 5 failures per IP → 15-min lockout |
| `POST /admin/api/logout` | ✓ | clears cookie |
| `GET  /admin/api/content` | ✓ | current `content.json` |
| `PUT  /admin/api/content` | ✓ | validate, write atomically, return normalised content |
| `GET  /admin/preview` | ✓ | renders current JSON to HTML, served inline |
| `POST /admin/api/publish` | ✓ | build → backup → atomic write → git sync in background |
| `GET  /admin/api/backups` | ✓ | last 20, newest first |
| `POST /admin/api/restore` | ✓ | `{name}` → backs up current, restores that `index.html` **and** its `content.json` |
| `GET  /admin/api/status` | ✓ | last publish, git sync result, whether content differs from what is live |

Every mutating route requires the cookie **and** the header
`X-Requested-With: ggmilad-admin`; with `SameSite=Strict` that closes CSRF.

**Auth.** One password. `ADMIN_PASSWORD_HASH` (argon2id) and
`SESSION_SECRET` live in `/opt/ggmilad-admin/.env`, never in git. The
session is an `itsdangerous` signed, timestamped cookie: `HttpOnly`,
`Secure`, `SameSite=Strict`, 12-hour life. Lockout state is in-memory —
fine with one worker. `admin/mkpass.py` prints a hash for a password read
from a prompt.

**Publish.** In order: render → write `index.html.new` in the webroot →
copy live `index.html` + current `content.json` to `backups/<UTC-ts>/` →
`os.replace` → `chmod 644`. Keep the newest 20 backup folders. Then a
background thread runs `git add content.json index.html && git commit &&
git push` with three attempts 5 s apart; the result lands in
`state.json` and shows in the panel. A failed push never fails a publish.

**Restore.** Restores both files from the chosen backup (after backing up
the current pair), so content and site never drift apart.

**UI.** One HTML file, `admin/static/admin.html`, RTL Persian, in the
portfolio's own visual language (same fonts, dark ground, the game-UI
framing). Three tabs — پروژه‌ها / لِوِل‌ها / سایت — plus a status bar
(published at, git sync, "unpublished changes" pill), **پیش‌نمایش**,
**انتشار**, and a backups drawer with **بازگردانی**. Projects list with
drag-to-reorder; each row expands to a form with fa/en fields side by
side. Every Save writes the JSON immediately; only Publish touches the
site.

## Server layout

```
/opt/ggmilad-admin/            git clone of the portfolio repo (deploy key)
  .venv/                       python -m venv
  .env                         ADMIN_PASSWORD_HASH, SESSION_SECRET (0600)
  content.json  template.html  build.py  admin/  index.html
  data/backups/<ts>/           index.html + content.json
  data/state.json
/var/www/ggmilad/index.html    the live site — owner ggadmin, group www-data, 664; dir 775
/etc/systemd/system/ggmilad-admin.service
```

nginx, inside the existing `ggon.top` 443 block:

```
location = /admin { return 301 /admin/; }
location /admin/ {
    proxy_pass         http://127.0.0.1:9914;
    proxy_set_header   Host $host;
    proxy_set_header   X-Real-IP $remote_addr;
    proxy_set_header   X-Forwarded-Proto https;
    client_max_body_size 2m;
}
```

Nothing else in the vhost changes. No `default_server`, no `_`.

The service runs as system user `ggadmin` with the same hardening block as
`tgdup.service`; `ReadWritePaths` = the repo dir and the webroot.

## The rule that keeps this coherent

After launch, **content** changes go through the panel and the server's
`content.json` is the truth; git follows it via the background push.
**Design** changes go through `template.html` locally → commit → push →
`git pull` on the server → Publish. Never edit `content.json` in two
places.

## Testing

- `tests/test_golden.py` — migration round-trip equals committed `index.html`.
- `tests/test_content.py` — schema rejects empty translations, bad enums,
  duplicate ids, non-https links; normalises chips.
- `tests/test_auth.py` — wrong password 401, lockout after 5, cookie
  required on every `✓` route, header required on mutations.
- `tests/test_publish.py` — publish writes atomically into a temp webroot,
  creates a backup pair, prunes to 20, restore swaps both files.
- Manual: run locally on `127.0.0.1:9914`, edit, preview, publish into a
  temp dir, restore.

## Rollout

1. Build and test locally; commit to `main`; push (this also pushes the
   held-back donate commit — harmless, the template now gates it).
2. On the VPS: create `ggadmin`, generate a deploy key, add it to the
   GitHub repo, clone to `/opt/ggmilad-admin`, venv, `.env`, systemd unit,
   nginx `location`, `nginx -t && reload`.
3. First publish from the panel with `donate_url` empty and p23 hidden.
   Verify the live page matches the previous live build apart from the
   coffee/donate diff.
4. When `donate.ggon.top` gets its A record: set `site.donate_url` in the
   panel, unhide p23, publish.
