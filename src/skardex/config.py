from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    database_url: str
    secret_key: str
    seed_admin_username: str
    seed_admin_password: str
    # Only needed on the day skardex.reset_admin_password is run; leave unset
    # otherwise.
    admin_reset_password: str | None = None
    # Must be True in production (Render serves over HTTPS). Defaults to
    # False so local dev over http://localhost keeps working out of the box.
    session_https_only: bool = False


settings = Settings()  # type: ignore[call-arg]
