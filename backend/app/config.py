from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = "postgresql+psycopg://support:support@db/support"
    public_url: str = "https://support.example.com"
    admin_username: str = "admin"
    admin_password: str = ""
    encryption_key: str = ""
    cookie_secure: bool = True
    upload_dir: str = "/data/uploads"
    max_upload_bytes: int = 5 * 1024 * 1024
    bark_allowed_hosts: str = "api.day.app"
    session_days: int = 30


@lru_cache
def settings():
    return Settings()
