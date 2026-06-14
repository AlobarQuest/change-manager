from fastapi import FastAPI

app = FastAPI(title="Change Manager")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
