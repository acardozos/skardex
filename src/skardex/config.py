from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    database_url: str
    secret_key: str
    seed_admin_username: str
    seed_admin_password: str


settings = Settings()  # type: ignore[call-arg]
