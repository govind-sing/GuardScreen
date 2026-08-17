from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    database_url: str
    redis_url: str
    idempotency_ttl_seconds: int = 3600  # 60 min, as we reasoned through above

    minio_endpoint: str
    minio_root_user: str
    minio_root_password: str
    minio_bucket: str

    arq_redis_url: str = "redis://redis:6379/1"

    groq_api_key: str

    class Config:
        env_file = ".env"

settings = Settings()