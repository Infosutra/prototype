from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=None,
        extra="ignore",
    )

    port: int = 8080
    database_path: str = "./data/infosutra.sqlite"
    log_level: str = "INFO"
    # Accept either name; start-local historically used KOBO_CREDENTIALS_ENCRYPTION_KEY
    secret_key: str = ""
    kobo_credentials_encryption_key: str = ""

    @property
    def encryption_key(self) -> str:
        # Prefer the persistent credentials key from start-local (.local/credentials.env).
        # SECRET_KEY alone is fine for one-off runs, but if both are set and differ,
        # using SECRET_KEY first caused stored tokens to become undecryptable after restart.
        return (
            self.kobo_credentials_encryption_key or self.secret_key
        ).strip()


@lru_cache
def get_settings() -> Settings:
    return Settings()
