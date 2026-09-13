import shutil
import time
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
    repo = tmp_path / "repo"
    repo.mkdir()
    shutil.copy(FIX / "golden-content.json", repo / "content.json")
    shutil.copy(FIX / "golden-template.html", repo / "template.html")
    static = repo / "admin" / "static"
    static.mkdir(parents=True)
    (static / "admin.html").write_text("<title>GGmilad Admin</title>", encoding="utf-8")
    s = Settings(
        repo_dir=repo, live_index=tmp_path / "web" / "index.html", data_dir=tmp_path / "data",
        password_hash=hash_password("pw"), session_secret="s", git_sync=False,
    )
    return TestClient(create_app(s), base_url="https://testserver")


def login(c):
    r = c.post("/admin/api/login", json={"password": "pw"}, headers=H)
    assert r.status_code == 204
    return c


def test_ui_served_without_auth(client):
    r = client.get("/admin/")
    assert r.status_code == 200 and "GGmilad Admin" in r.text
    assert client.get("/admin", follow_redirects=False).status_code == 301


def test_api_requires_session(client):
    assert client.get("/admin/api/content").status_code == 401
    assert client.get("/admin/preview").status_code == 401
    assert client.post("/admin/api/publish", headers=H).status_code == 401


def test_wrong_password_401_then_lockout(client):
    for _ in range(5):
        assert client.post("/admin/api/login", json={"password": "x"}, headers=H).status_code == 401
    assert client.post("/admin/api/login", json={"password": "pw"}, headers=H).status_code == 429


def test_login_requires_header(client):
    assert client.post("/admin/api/login", json={"password": "pw"}).status_code == 403


def test_login_sets_cookie_and_content_readable(client):
    login(client)
    r = client.get("/admin/api/content")
    assert r.status_code == 200
    assert r.json()["content"]["projects"][0]["id"] == "p1"
    assert r.json()["next_project_id"] == "p24"


def test_mutation_requires_header(client):
    login(client)
    body = client.get("/admin/api/content").json()["content"]
    assert client.put("/admin/api/content", json=body).status_code == 403
    assert client.put("/admin/api/content", json=body, headers=H).status_code == 200


def test_put_validates_and_persists(client):
    login(client)
    body = client.get("/admin/api/content").json()["content"]
    body["projects"][0]["title"]["en"] = ""
    r = client.put("/admin/api/content", json=body, headers=H)
    assert r.status_code == 422 and r.json()["detail"][0]["loc"][:3] == ["projects", 0, "title"]
    body["projects"][0]["title"]["en"] = "Changed"
    r = client.put("/admin/api/content", json=body, headers=H)
    assert r.status_code == 200
    assert r.json()["content"]["projects"][0]["title"]["en"] == "Changed"
    assert r.json()["dirty"] is True
    assert client.get("/admin/api/content").json()["content"]["projects"][0]["title"]["en"] == "Changed"


def test_preview_publish_status(client):
    login(client)
    assert "<article" in client.get("/admin/preview").text
    r = client.post("/admin/api/publish", headers=H)
    assert r.status_code == 200 and r.json()["bytes"] > 1000
    st = client.get("/admin/api/status").json()
    assert st["dirty"] is False and st["last_publish"] and st["live_bytes"] == r.json()["bytes"]


def test_backups_and_restore(client):
    login(client)
    client.post("/admin/api/publish", headers=H)
    body = client.get("/admin/api/content").json()["content"]
    body["projects"][0]["mark"] = "🧪"
    client.put("/admin/api/content", json=body, headers=H)
    time.sleep(1.05)
    client.post("/admin/api/publish", headers=H)
    names = [b["name"] for b in client.get("/admin/api/backups").json()]
    assert len(names) == 2
    assert client.post("/admin/api/restore", json={"name": names[0]}, headers=H).status_code == 200
    assert client.get("/admin/api/content").json()["content"]["projects"][0]["mark"] != "🧪"
    assert client.post("/admin/api/restore", json={"name": "../x"}, headers=H).status_code == 422
    assert client.post("/admin/api/restore", json={"name": "20200101T000000Z"}, headers=H).status_code == 404


def test_logout(client):
    login(client)
    assert client.post("/admin/api/logout", headers=H).status_code == 204
    assert client.get("/admin/api/content").status_code == 401


def test_no_docs_exposed(client):
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404
