from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    PROJECT_NAME: str = "BidEasy"
    PROJECT_VERSION: str = "2.2.0"
    API_V1_STR: str = "/api/v1"
    
    # CORS
    BACKEND_CORS_ORIGINS: list[str] = ["http://localhost", "http://localhost:8080", "http://localhost:3000", "*"]
    
    # Database
    POSTGRES_SERVER: str = "localhost"
    POSTGRES_USER: str = "bideasy"
    POSTGRES_PASSWORD: str = "bideasy_pass"
    POSTGRES_DB: str = "bideasy_db"
    
    # Redis
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379

    # OpenAI
    OPENAI_API_KEY: str = ""

    class Config:
        env_file = ".env"

settings = Settings()
