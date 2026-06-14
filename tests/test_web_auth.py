from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

import app.web_auth as wa
from app.web_auth import current_user


def _app():
    app = FastAPI()

    @app.get("/whoami")
    def whoami(user: str = Depends(current_user)):
        return {"user": user}

    return TestClient(app)


def test_reads_user_from_sso_header():
    wa.settings.dev_user = ""
    c = _app()
    r = c.get("/whoami", headers={"X-authentik-email": "devon@x"})
    assert r.status_code == 200 and r.json() == {"user": "devon@x"}


def test_missing_header_no_dev_user_is_401():
    wa.settings.dev_user = ""
    assert _app().get("/whoami").status_code == 401


def test_dev_user_fallback_when_no_header():
    wa.settings.dev_user = "dev@local"
    r = _app().get("/whoami")
    assert r.status_code == 200 and r.json() == {"user": "dev@local"}
