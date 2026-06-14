from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./change_manager.db"
    m2m_token: str = ""  # required in prod; empty disables auth in local dev
    sso_user_header: str = "x-authentik-email"  # forward-auth header Authentik sets
    dev_user: str = ""  # local-dev fallback identity when no SSO header (empty = disabled)


settings = Settings()
