from datetime import UTC, datetime

from fastapi import Header, HTTPException, Request, status

from app.bearers import scope_for
from app.config import settings
from app.scopes import FULL, SCOPE_ROUTES


def require_m2m(request: Request, authorization: str | None = Header(default=None)) -> None:
    """Authenticate the bearer, then confine it to what its scope may reach.

    `app/bearers.py` holds what a bearer authenticates as, and its fail-closed properties: an
    unset or unparseable variable grants nothing, an empty bearer grants nothing, and a value
    configured for two scopes resolves to the narrower one.

    Two different failures, two different codes, and the distinction is load-bearing: 401 means
    "this credential is not recognised" and sends an operator to rotate something, while 403 means
    "recognised, and not allowed here" and sends them to the scope table. Collapsing them would
    make a correctly-configured producer hitting a door it may not open look like a bad secret.

    Keyed on the matched route TEMPLATE, so the rule reads the same as `scopes.py` lists it. A
    request that matched no route yields `None`, which is in no allowlist -- the unknown case
    refuses. Raised as `HTTPException` directly because this application registers no exception
    handlers, so a custom exception would surface as a bare 500.
    """
    token = ""
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    scope = scope_for(token, settings, datetime.now(UTC))
    if scope is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid M2M token")
    if scope == FULL:
        return
    matched = getattr(request.scope.get("route"), "path", None)
    if (request.method, matched) not in SCOPE_ROUTES[scope]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"the '{scope}' credential may not {request.method} {matched or 'this route'}",
        )
