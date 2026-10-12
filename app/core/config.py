from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: SecretStr
    read_database_url: SecretStr

    llm_api_key: SecretStr | None = None
    llm_base_url: str = "https://ark.cn-beijing.volces.com/api/plan/v3"  
    llm_model: str | None = None

settings = Settings()