import os
from datetime import UTC, datetime

from fastapi import FastAPI

from app.api import router as api_router
from app.bearers import check_at_boot
from app.config import settings
from app.web import router as web_router

# A bearer setting that breaks a rule must stop boot (`app/bearers.py`). Checked at import so the
# container fails to start rather than serving with every bearer refused.
check_at_boot(settings, datetime.now(UTC))

app = FastAPI(title="Change Manager")

app.include_router(api_router)
app.include_router(web_router)


@app.get("/api/health")
def health() -> dict[str, str]:
    """Liveness, plus WHICH build is answering.

    The revision is what makes a post-deploy check able to fail. Coolify serves the
    old container throughout a swap, so a poll for `status == "ok"` alone returns 200
    the entire time and passes whether or not the new image ever started. `deploy.yml`
    polls until this reports the commit it just built.

    Unset outside a built image (local runs, tests), where there is no revision to report.
    """
    return {"status": "ok", "revision": os.environ.get("GIT_SHA", "unknown")}
