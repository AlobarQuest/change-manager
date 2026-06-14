from fastapi import FastAPI

from app.api import router as api_router
from app.web import router as web_router

app = FastAPI(title="Change Manager")

app.include_router(api_router)
app.include_router(web_router)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
