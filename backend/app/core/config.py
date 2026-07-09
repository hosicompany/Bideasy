import secrets
from pydantic import model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    PROJECT_NAME: str = "BidEasy"
    PROJECT_VERSION: str = "2.3.0"
    API_V1_STR: str = "/api/v1"
    APP_ENV: str = "development"  # development | production

    # === Security ===
    # 운영(production)에서는 반드시 환경변수로 주입해야 한다(아래 validator 가 강제).
    # 미설정 시 dev/test 에서만 임시 랜덤 키를 생성 — 운영에서 비면 기동 실패.
    JWT_SECRET_KEY: str = ""

    # 빌링키 at-rest 암호화 키(Fernet). 비어 있으면 평문 저장(기존 동작).
    # 설정 시 신규 빌링키는 암호화 저장, 레거시 평문은 자동 폴백 복호화. → app/core/crypto.py
    BILLING_ENC_KEY: str = ""
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

    # 자동결제(빌링) 전용 키 — 빌링 MID(bill_bideaid9e) 승인 후 발급되는 키.
    # 비어 있으면 일반 결제 키로 fallback (토스 테스트키는 단건·빌링 모두 지원하므로
    # 테스트 환경에서는 TOSS_CLIENT_KEY/SECRET_KEY 만으로 빌링 E2E 가능).
    TOSS_BILLING_CLIENT_KEY: str = ""
    TOSS_BILLING_SECRET_KEY: str = ""

    @property
    def toss_billing_client_key(self) -> str:
        return self.TOSS_BILLING_CLIENT_KEY or self.TOSS_CLIENT_KEY

    @property
    def toss_billing_secret_key(self) -> str:
        return self.TOSS_BILLING_SECRET_KEY or self.TOSS_SECRET_KEY

    # === 결제 PG 선택 ===
    # toss | payple — 정기결제(빌링)에 사용할 PG. 토스 빌링 심사 대기 동안
    # 페이플(심사 7일~2주)로 먼저 출시 가능. 기본 toss(기존 동작 유지).
    PAYMENT_PROVIDER: str = "toss"

    # === Payple (페이플) 정기결제 ===
    # 기본값은 공개 테스트 샌드박스. 가맹 승인 후 라이브 값으로 교체.
    PAYPLE_IS_TEST: bool = True
    PAYPLE_CST_ID: str = "test"
    PAYPLE_CUST_KEY: str = "abcd1234567890"
    PAYPLE_CLIENT_KEY: str = "test_DF55F29DA654A8CBC0F0A9DD4B556486"
    # Referer 화이트리스트 — 페이플에 등록된 도메인과 일치해야 함(불일치 시 AUTH0004)
    PAYPLE_REFERER: str = "https://bideasy.kr"

    @property
    def payple_host(self) -> str:
        return "https://democpay.payple.kr" if self.PAYPLE_IS_TEST else "https://cpay.payple.kr"

    # === Admin daily report ===
    # 슬랙 incoming webhook URL (옵션). 없으면 in-app Notification 만 발송.
    SLACK_WEBHOOK_URL: str = ""

    # === ML Models ===
    ML_MODELS_PATH: str = "./models"
    HISTORICAL_DB_PATH: str = "./data/historical/bid_results_5years.db"

    # === Rate Limiting ===
    AI_ANALYSIS_FREE_LIMIT: int = 1  # Free tier: 1 AI analysis per day

    # === 블로그 자동발행 ===
    # 데이터스토리 자동 초안에 부여할 유예 시간(시간). 이 시간이 지나도록 사람이
    # 발행/삭제하지 않으면 스케줄러가 자동 발행한다. 0 이하면 유예 부여 안 함
    # (=현행 draft 유지, 킬스위치). 상록수 예약 드립은 admin 이 publish_at 을 직접 지정.
    BLOG_AUTOPUBLISH_GRACE_HOURS: int = 48

    # === Firebase (FCM Push Notifications) ===
    FIREBASE_CREDENTIALS_JSON: str = ""  # Path to service account JSON file

    # === Monitoring ===
    SENTRY_DSN: str = ""  # Leave empty to disable Sentry

    # === SEO (검색엔진 소유확인) ===
    # 빈 값이면 메타태그 미출력. Google Search Console / 네이버 서치어드바이저 코드.
    GOOGLE_SITE_VERIFICATION: str = ""
    NAVER_SITE_VERIFICATION: str = ""

    # === Logging ===
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "text"  # "json" | "text"

    @model_validator(mode="after")
    def _enforce_production_secrets(self):
        """운영(production)에서 필수 시크릿 누락 시 기동 실패(fail-fast).

        dev/test 에서 JWT_SECRET_KEY 미설정 시에는 임시 랜덤 키를 생성해 편의를 유지하되,
        운영에서는 반드시 명시적으로 주입하도록 강제한다(워커별 키 불일치·재시작 시 전원
        로그아웃 같은 조용한 사고 방지).
        """
        if self.APP_ENV == "production":
            missing = []
            if not self.JWT_SECRET_KEY:
                missing.append("JWT_SECRET_KEY")
            if self.DATABASE_MODE == "postgresql" and self.POSTGRES_PASSWORD in ("", "bideasy_pass"):
                missing.append("POSTGRES_PASSWORD")
            if missing:
                raise ValueError(
                    "production 환경에 필수 시크릿이 설정되지 않았습니다: "
                    + ", ".join(missing)
                )
        elif not self.JWT_SECRET_KEY:
            self.JWT_SECRET_KEY = secrets.token_urlsafe(32)
        return self

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
