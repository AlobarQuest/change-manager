from collections.abc import Callable, Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.db import Base, get_db
from app.main import app


@pytest.fixture()
def db() -> Iterator[Session]:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client(db: Session) -> Iterator[TestClient]:
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def m2m() -> dict[str, str]:
    """Authorize the /api routes, and hand back the header to send."""
    import app.auth as auth

    auth.settings.m2m_token = "testtok"
    return {"Authorization": "Bearer testtok"}


# A well-formed deploying-merge proposal (ADR-0019), modelled on the change it will
# first carry: change-manager's own pull request #42.
_DEPLOY_PAYLOAD = {
    "target_repository": "AlobarQuest/change-manager",
    "pull_request_number": 42,
    "change_class": "dependency-update",
    "risk": "caution",
    "reasoning": "uvicorn floor bump; landing on main redeploys production",
    "acceptance_criteria": ["/api/health reports the merged commit within 10 minutes"],
    "rollback_plan": {"steps": ["re-point :main at the previous :<sha>", "revert the merge"]},
    "actor": "test",
}


@pytest.fixture()
def deploy_payload() -> Callable[..., dict]:
    """Build that proposal, bending any field. A dict rather than a model, so the
    refusal tests can send shapes the model would never let them construct."""

    def build(**overrides) -> dict:
        return {**_DEPLOY_PAYLOAD, **overrides}

    return build
