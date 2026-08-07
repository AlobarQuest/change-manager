from fastapi.testclient import TestClient

from app.main import app


def test_health():
    r = TestClient(app).get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_health_reports_the_running_revision(monkeypatch):
    """deploy.yml polls this field to tell the new container from the old one."""
    monkeypatch.setenv("GIT_SHA", "abc123")
    assert TestClient(app).get("/api/health").json()["revision"] == "abc123"


def test_health_revision_is_unknown_outside_a_built_image(monkeypatch):
    monkeypatch.delenv("GIT_SHA", raising=False)
    assert TestClient(app).get("/api/health").json()["revision"] == "unknown"
