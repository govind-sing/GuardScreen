from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    database_url: str
    redis_url: str
    idempotency_ttl_seconds: int = 3600  # 60 min, as we reasoned through above

    class Config:
        env_file = ".env"

settings = Settings()