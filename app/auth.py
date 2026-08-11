from fastapi import Header, HTTPException, Request, status

from app.config import settings
from app.scopes import FULL, OBSERVE, PROPOSE, READ, SCOPE_ROUTES


def _token_scopes() -> dict[str, str]:
    """Map each CONFIGURED bearer to its scope, skipping every unset one.

    **An unset secret must grant nothing.** `require_m2m` has always had that property for the
    full token through its `if not expected` clause; a map built without the same care binds `""`
    to a scope, and `Authorization: Bearer ` with a trailing space yields exactly `""` after the
    strip below. The falsy check here is what keeps a repository that configures only some of the
    scopes -- which is every repository today -- from handing the rest to an empty bearer.

    Narrow scopes are inserted FIRST so that a value configured for two scopes resolves to the
    narrower one. Sharing a value is not expected, but the orchestrator already does it
    deliberately for two observer credentials, so the collision is resolved in the fail-closed
    direction rather than left to dict ordering.
    """
    configured = (
        (settings.m2m_token_read, READ),
        (settings.m2m_token_propose, PROPOSE),
        (settings.m2m_token_observe, OBSERVE),
        (settings.m2m_token, FULL),
    )
    scopes: dict[str, str] = {}
    for token, scope in configured:
        if token:
            scopes.setdefault(token, scope)
    return scopes


def require_m2m(request: Request, authorization: str | None = Header(default=None)) -> None:
    """Authenticate the bearer, then confine it to what its scope may reach.

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
    scope = _token_scopes().get(token) if token else None
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
