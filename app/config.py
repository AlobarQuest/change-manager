from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./change_manager.db"
    m2m_token: str = ""  # required in prod; empty disables auth in local dev


settings = Settings()
