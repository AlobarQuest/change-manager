from pathlib import Path


def test_entrypoint_migrates_before_serving():
    text = Path("entrypoint.sh").read_text()
    mig = text.index("alembic upgrade head")
    serve = text.index("uvicorn app.main:app")
    assert mig < serve, "migrations must run before uvicorn starts"
    assert "--port 8000" in text


def test_dockerfile_pins_base_and_runs_nonroot():
    df = Path("Dockerfile").read_text()
    assert ":latest" not in df  # rule #3
    assert "USER appuser" in df
    assert "EXPOSE 8000" in df
