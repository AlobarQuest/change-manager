# Machine bearer settings

change-manager authenticates four machine bearers, one per scope. Each Coolify variable holds the
bearer's sha256 hash, never the bearer (ADR-0055 decision 7, amendment 9 decision 6, in the
orchestrator repository). `app/bearers.py` holds the rules, and
`tests/fixtures/m2m_bearer_setting.json` pins them with the orchestrator.

| Variable | Scope (the entry key) |
|---|---|
| `M2M_TOKEN` | `full` |
| `M2M_TOKEN_READ` | `read` |
| `M2M_TOKEN_PROPOSE` | `propose` |
| `M2M_TOKEN_OBSERVE` | `observe` |

## The value

One JSON object with one entry, keyed by the variable's scope:

```json
{"read": {"token_hash": "<sha256 hex of the bearer>"}}
```

During a rotation's overlap, the entry also holds the old bearer's hash and when it stops working:

```json
{"read": {"token_hash": "<new>", "previous": {"token_hash": "<old>", "until": "<UTC ISO 8601>"}}}
```

- The hash is of the bearer exactly as a client sends it after `Bearer `, with surrounding
  whitespace removed: lowercase hex, 64 characters.
- `previous` is accepted only before `until`. An `until` already past authenticates nothing.
- A variable that doesn't parse grants nothing for its scope; the other scopes keep working. The
  service logs `<VARIABLE> doesn't parse` on each request until it's fixed.
- Boot refuses a `previous` hash equal to any scope's current hash, and an `until` more than eight
  days ahead. While either holds, every bearer is refused.

Each variable has two rows in Coolify (`is_preview` false and true). Write both, then restart: a
variable edit has no effect until the next restart or deploy.

## Roll back past the hashed form

An image built before `app/bearers.py` reads each variable as a plaintext bearer. With the
variables holding JSON, that image accepts the JSON text itself as a bearer, which anyone who can
read the setting can build, and refuses every real bearer. Before rolling back to such an image,
rewrite each variable to its plaintext bearer from its BWS keeper (`.cred-consumers.toml` names the
UUIDs), then deploy the older image.

Rolling forward again needs the reverse. An image that holds only the hashed form refuses a plaintext
value, so rewrite each variable back to its hashed value before deploying it. The image from
change-manager #115 reads both forms, so it's the safe image to stand on while the variables hold
either.
