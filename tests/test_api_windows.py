import app.auth as auth

H = {"Authorization": "Bearer t"}


def test_create_then_finish_window_run(client):
    auth.settings.m2m_token = "t"
    r = client.post("/api/window-runs", headers=H, json={"started_at": "2026-06-14T04:00:00Z"})
    assert r.status_code == 200
    wid = r.json()["id"]
    assert r.json()["status"] == "running"
    p = client.patch(f"/api/window-runs/{wid}", headers=H,
                     json={"status": "done", "considered": 3, "applied": 1, "failed": 0,
                           "blocked": 2, "skipped": 0, "report_md": "# digest"})
    assert p.status_code == 200
    assert p.json()["status"] == "done" and p.json()["applied"] == 1
