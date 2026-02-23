import secrets
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    PROJECT_NAME: str = "BidEasy"
    PROJECT_VERSION: str = "2.3.0"
    API_V1_STR: str = "/api/v1"
    APP_ENV: str = "development"  # development | production

    # === Security ===
    JWT_SECRET_KEY: str = secrets.token_urlsafe(32)
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days

    # === CORS ===
    BACKEND_CORS_ORIGINS: list[str] = [
        "http://localhost",
        "http://localhost:3000",
        "http://localhost:5000",
        "http://localhost:8080",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5000",
        "http://127.0.0.1:8080",
    ]

    # === Database ===
    DATABASE_MODE: str = "sqlite"  # "sqlite" | "postgresql"
    SQLITE_URL: str = "sqlite:///./bideasy.db"
    POSTGRES_SERVER: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str = "bideasy"
    POSTGRES_PASSWORD: str = "bideasy_pass"
    POSTGRES_DB: str = "bideasy_db"

    @property
    def database_url(self) -> str:
        if self.DATABASE_MODE == "postgresql":
            return (
                f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
                f"@{self.POSTGRES_SERVER}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
            )
        return self.SQLITE_URL

    # === Redis ===
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0

    @property
    def redis_url(self) -> str:
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    # === Celery ===
    CELERY_BROKER_URL: str = ""
    CELERY_RESULT_BACKEND: str = ""

    @property
    def celery_broker(self) -> str:
        return self.CELERY_BROKER_URL or self.redis_url

    @property
    def celery_backend(self) -> str:
        return self.CELERY_RESULT_BACKEND or self.redis_url

    # === External APIs ===
    OPENAI_API_KEY: str = ""
    PUBLIC_DATA_KEY: str = ""

    # === OAuth (Social Login) ===
    KAKAO_REST_API_KEY: str = ""
    KAKAO_CLIENT_SECRET: str = ""
    KAKAO_NATIVE_APP_KEY: str = ""  # Flutter mobile SDK (not used by backend)
    NAVER_CLIENT_ID: str = ""
    NAVER_CLIENT_SECRET: str = ""
    FRONTEND_URL: str = "http://localhost:5000"
    BACKEND_URL: str = "http://127.0.0.1:8000"  # OAuth callback base URL

    # === Toss Payments ===
    TOSS_CLIENT_KEY: str = ""
    TOSS_SECRET_KEY: str = ""
    TOSS_WEBHOOK_SECRET: str = ""

    # === ML Models ===
    ML_MODELS_PATH: str = "./models"
    HISTORICAL_DB_PATH: str = "./data/historical/bid_results_5years.db"

    # === Rate Limiting ===
    AI_ANALYSIS_FREE_LIMIT: int = 1  # Free tier: 1 AI analysis per day

    # === Logging ===
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "text"  # "json" | "text"

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
