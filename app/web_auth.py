from fastapi import HTTPException, Request, status

from app.config import settings


def current_user(request: Request) -> str:
    """The SSO-authenticated email from the forward-auth header, or the dev fallback.

    401 if neither.
    """
    email = request.headers.get(settings.sso_user_header, "").strip()
    if email:
        return email
    if settings.dev_user:
        return settings.dev_user
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="not authenticated (SSO)")
