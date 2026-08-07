import os

from fastapi import FastAPI

from app.api import router as api_router
from app.web import router as web_router

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
