"""The HTTP surface. Everything lives under /admin; nginx proxies only that
prefix, so nothing here ever answers on the public site's paths."""
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, ValidationError

from build import render
from admin.auth import Lockout, Sessions, verify_password
from admin.config import Settings
from admin.content import Content, content_hash, load_content, next_project_id, save_content
from admin.publish import list_backups, load_state, publish, restore

COOKIE = "gg_admin"
HEADER, HEADER_VALUE = "x-requested-with", "ggmilad-admin"
STATIC = Path(__file__).parent / "static"


class LoginBody(BaseModel):
    password: str


class RestoreBody(BaseModel):
    name: str


def create_app(s: Settings) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    sessions = Sessions(s.session_secret, s.session_max_age)
    lockout = Lockout()
    # tests point repo_dir at a temp copy that carries its own admin.html
    static_dir = s.repo_dir / "admin" / "static"
    if not (static_dir / "admin.html").exists():
        static_dir = STATIC

    def client_ip(req: Request) -> str:
        return req.headers.get("x-real-ip") or (req.client.host if req.client else "?")

    def require_session(req: Request):
        if not sessions.check(req.cookies.get(COOKIE)):
            raise HTTPException(401, "not signed in")

    def require_header(req: Request):
        if req.headers.get(HEADER) != HEADER_VALUE:
            raise HTTPException(403, "missing X-Requested-With header")

    def current() -> Content:
        return load_content(s.content_path)

    def is_dirty(c: Content) -> bool:
        return load_state(s).get("published_hash") != content_hash(c)

    def envelope(c: Content) -> dict:
        return {"content": c.model_dump(), "dirty": is_dirty(c), "next_project_id": next_project_id(c)}

    session_only = [Depends(require_session)]
    mutation = [Depends(require_session), Depends(require_header)]

    @app.get("/admin", include_in_schema=False)
    def root_redirect():
        return RedirectResponse("/admin/", status_code=301)

    @app.get("/admin/", response_class=HTMLResponse)
    def ui():
        return FileResponse(static_dir / "admin.html", media_type="text/html; charset=utf-8",
                            headers={"Cache-Control": "no-store"})

    @app.post("/admin/api/login", dependencies=[Depends(require_header)])
    def login(body: LoginBody, req: Request):
        ip = client_ip(req)
        if lockout.is_locked(ip):
            raise HTTPException(429, "too many attempts; try again in 15 minutes")
        if not verify_password(s.password_hash, body.password):
            lockout.record_failure(ip)
            raise HTTPException(401, "wrong password")
        lockout.reset(ip)
        resp = Response(status_code=204)
        resp.set_cookie(COOKIE, sessions.issue(), max_age=s.session_max_age, path="/admin",
                        httponly=True, secure=True, samesite="strict")
        return resp

    @app.post("/admin/api/logout", dependencies=mutation)
    def logout():
        resp = Response(status_code=204)
        resp.delete_cookie(COOKIE, path="/admin")
        return resp

    @app.get("/admin/api/content", dependencies=session_only)
    def get_content():
        return envelope(current())

    @app.put("/admin/api/content", dependencies=mutation)
    def put_content(body: dict):
        try:
            c = Content.model_validate(body)
        except ValidationError as e:
            return JSONResponse({"detail": e.errors(include_url=False, include_input=False)}, status_code=422)
        save_content(c, s.content_path)
        return envelope(c)

    @app.get("/admin/preview", response_class=HTMLResponse, dependencies=session_only)
    def preview():
        return HTMLResponse(render(current().model_dump(), s.template_path), headers={"Cache-Control": "no-store"})

    @app.post("/admin/api/publish", dependencies=mutation)
    def do_publish():
        r = publish(s, current())
        r["state"] = load_state(s)
        return r

    @app.get("/admin/api/backups", dependencies=session_only)
    def backups():
        return list_backups(s)

    @app.post("/admin/api/restore", dependencies=mutation)
    def do_restore(body: RestoreBody):
        try:
            r = restore(s, body.name)
        except ValueError:
            raise HTTPException(422, "bad backup name")
        except FileNotFoundError:
            raise HTTPException(404, "no such backup")
        r["state"] = load_state(s)
        return r

    @app.get("/admin/api/status", dependencies=session_only)
    def status():
        st = load_state(s)
        return {
            "last_publish": st.get("last_publish"),
            "last_publish_bytes": st.get("last_publish_bytes"),
            "git_sync": st.get("git_sync"),
            "restored_from": st.get("restored_from"),
            "dirty": is_dirty(current()),
            "live_bytes": s.live_index.stat().st_size if s.live_index.exists() else 0,
        }

    return app
