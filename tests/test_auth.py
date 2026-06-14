from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.auth import require_m2m


def _app(token: str):
    import app.auth as a
    a.settings.m2m_token = token  # set the expected token for the test
    app = FastAPI()

    @app.get("/protected", dependencies=[Depends(require_m2m)])
    def protected():
        return {"ok": True}

    return TestClient(app)


def test_missing_token_is_401():
    c = _app("secret")
    assert c.get("/protected").status_code == 401


def test_wrong_token_is_401():
    c = _app("secret")
    assert c.get("/protected", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_correct_token_passes():
    c = _app("secret")
    assert c.get("/protected", headers={"Authorization": "Bearer secret"}).status_code == 200
