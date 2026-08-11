from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./change_manager.db"
    m2m_token: str = ""  # required in prod; empty disables auth in local dev
    # Narrow machine credentials (ADR-0019 increment 4, task zero). Each is OPTIONAL and each
    # defaults to empty, which grants NOTHING -- see `auth._token_scopes`. What they may reach is
    # `app/scopes.py`; none of them can approve a change record, which is the property the
    # increment exists to establish before it ships a producer of those records.
    m2m_token_read: str = ""
    m2m_token_propose: str = ""
    m2m_token_observe: str = ""
    sso_user_header: str = "x-authentik-email"  # forward-auth header Authentik sets
    dev_user: str = ""  # local-dev fallback identity when no SSO header (empty = disabled)
    # HANDOFF_WATCHDOG_DAYS: revert stale handed_off items to pending
    handoff_watchdog_days: int = 7


settings = Settings()
