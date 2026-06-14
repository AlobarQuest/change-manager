from fastapi import Header, HTTPException, status

from app.config import settings


def require_m2m(authorization: str | None = Header(default=None)) -> None:
    """Validate the mini's M2M bearer token. Raises 401 on mismatch."""
    expected = settings.m2m_token
    token = ""
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    if not expected or token != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid M2M token")
