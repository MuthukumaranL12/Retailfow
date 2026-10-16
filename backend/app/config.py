from functools import lru_cache

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "RetailFlow API"
    environment: str = Field(default="development", alias="APP_ENV")
    api_v1_str: str = "/api/v1"
    secret_key: str = Field(default="development-secret-key", alias="SECRET_KEY")
    algorithm: str = Field(default="HS256", alias="JWT_ALGORITHM")
    access_token_expire_minutes: int = Field(default=60, alias="ACCESS_TOKEN_EXPIRE_MINUTES")
    refresh_token_expire_days: int = Field(default=7, alias="REFRESH_TOKEN_EXPIRE_DAYS")
    mongodb_uri: str = Field(default="mongodb://localhost:27017", alias="MONGODB_URI")
    mongo_db_name: str = Field(default="retailflow", alias="MONGO_DB_NAME")
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")
    kafka_bootstrap_servers: str = Field(default="localhost:9092", alias="KAFKA_BOOTSTRAP_SERVERS")
    llm_provider: str = Field(default="openai", alias="LLM_PROVIDER")
    llm_model: str = Field(default="gpt-4o-mini", alias="LLM_MODEL")
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    cors_origins: str = Field(default="http://localhost:5173", alias="CORS_ORIGINS")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @model_validator(mode="after")
    def validate_production_secret(self):
        if self.environment.lower() in {"prod", "production"} and (
            self.secret_key == "development-secret-key" or len(self.secret_key) < 32
        ):
            raise ValueError("Production requires a unique SECRET_KEY of at least 32 characters")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
