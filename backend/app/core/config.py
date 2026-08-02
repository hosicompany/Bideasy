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
    # ⚠️ DEPRECATED (2026-08-02) — OpenAI 직결 폐지. 코드에서 더 이상 읽지 않는다.
    # 필드만 남긴 이유: 서버 .env 에 이 키가 남아 있어도 기동이 깨지지 않게 하기 위함.
    # 서버 정리가 끝나면 이 줄을 지워도 된다.
    OPENAI_API_KEY: str = ""

    # === LLM 게이트웨이 — 전 기능이 OpenRouter 한 곳을 경유 (services/llm_gateway.py) ===
    # 공고 요약·독소조항, 첨부 심층분석, 고객 챗봇, 블로그 정본·채널 파생 전부.
    # 비워두면 아래 CONTENT_LLM_* 를 그대로 쓴다(구 배포 무중단 호환).
    LLM_API_KEY: str = ""      # OpenRouter 키. 서버 .env.production 에만.
    LLM_BASE_URL: str = ""     # 예: https://openrouter.ai/api/v1
    # 용도별 모델 (OpenRouter 표기 — 프로바이더 접두사 필수)
    LLM_MODEL_ANALYSIS: str = "openai/gpt-4o-mini"   # 공고 3줄 요약·독소조항 (Pro)
    LLM_MODEL_DEEP: str = "openai/gpt-5-nano"        # 첨부 심층분석 (Pro+, 롱컨텍스트)
    LLM_MODEL_SUPPORT: str = "openai/gpt-4o-mini"    # 고객 챗봇 (저지연 우선)
    # 추론형 모델은 reasoning 에 토큰을 먼저 쓴다 — 넉넉해야 본문이 빈 채로 오지 않는다.
    LLM_MAX_TOKENS_DEEP: int = 16000

    # 콘텐츠 엔진(블로그 정본) 작성 모델 — 브랜드 얼굴이라 상위 모델.
    # 2026-08-02 모델 비교(7종 동일 주제) 결과 Sonnet 5 유지 확정 — docs/CONTENT_ENGINE.md
    #   CONTENT_LLM_MODEL=anthropic/claude-sonnet-5
    #   LLM_BASE_URL=https://openrouter.ai/api/v1
    #   LLM_API_KEY=<OpenRouter 키; 서버 .env.production 에만>
    CONTENT_LLM_MODEL: str = "anthropic/claude-sonnet-5"
    # 정본 외 가벼운 콘텐츠 호출용 저가 모델 — 채널 파생·주제 제안·주간 서술.
    CONTENT_LLM_CHEAP_MODEL: str = "openai/gpt-4o-mini"
    CONTENT_LLM_BASE_URL: str = ""   # (구 설정) LLM_BASE_URL 이 비면 이 값을 쓴다
    CONTENT_LLM_API_KEY: str = ""    # (구 설정) LLM_API_KEY 가 비면 이 값을 쓴다
    PUBLIC_DATA_KEY: str = ""

    # === IndexNow (색인 통보 — 네이버·Bing 등) ===
    # ⚠️ 이 키는 **비밀이 아니다.** 프로토콜상 https://bideasy.kr/{KEY}.txt 로 공개해야
    # 소유 증명이 성립한다. 값을 바꾸면 infra/nginx/html/{KEY}.txt 도 함께 바꿔야 한다.
    # 발송은 APP_ENV=production 에서만(services/indexnow.is_enabled).
    INDEXNOW_KEY: str = "1ba9903f6def627dc5124779539223ee"
    INDEXNOW_ENDPOINTS: list[str] = [
        "https://searchadvisor.naver.com/indexnow",  # 네이버 직접(비치헤드 주 채널)
        "https://api.indexnow.org/indexnow",          # 참여 검색엔진 공유(Bing 등)
    ]

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
    # 주간 데이터스토리 발행에 필요한 최소 개찰 건수. 미만이면 초안을 만들지 않는다
    # (docs/CONTENT_ENGINE.md §9.2 — 얇거나 서로 비슷한 주간 페이지는 구글 스팸정책
    # doorway/중복 판정 리스크). 정상 주는 수천 건이라 이 값은 '크롤 실패한 주'만 걸러낸다.
    # 0 이하면 게이트 해제.
    BLOG_MIN_WEEKLY_RECORDS: int = 30

    # === Firebase (FCM Push Notifications) ===
    FIREBASE_CREDENTIALS_JSON: str = ""  # Path to service account JSON file

    # === Monitoring ===
    SENTRY_DSN: str = ""  # Leave empty to disable Sentry

    # === SEO (검색엔진 소유확인) ===
    # 빈 값이면 메타태그 미출력. Google Search Console / 네이버 서치어드바이저 코드.
    GOOGLE_SITE_VERIFICATION: str = ""
    NAVER_SITE_VERIFICATION: str = ""

    # === 아웃바운드 이메일 (AWS SES) ===
    # 킬스위치: False 면 실제 전송 없이 dry-run 로그만 남긴다(기본값 — 오발송 방지).
    # SES 프로덕션 액세스 승인 + 도메인 DKIM 인증이 끝난 뒤에만 True 로 켠다.
    OUTBOUND_EMAIL_ENABLED: bool = False
    AWS_REGION: str = "ap-northeast-2"
    # 자격증명은 IAM 역할이 있으면 비워둔다(boto3 기본 체인). Lightsail 은 키 주입 필요.
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""
    SES_FROM_EMAIL: str = "no-reply@bideasy.kr"
    SES_FROM_NAME: str = "BidEasy"
    SES_REPLY_TO: str = "support@bideasy.kr"
    SES_CONFIGURATION_SET: str = ""   # 반송·수신거부 이벤트 추적용(선택)
    # 반송·불만 알림 SNS 토픽 ARN. 설정하면 이 토픽에서 온 메시지만 웹훅이 수용한다
    # (다른 AWS 계정의 유효 서명 메시지까지 막는 마지막 자물쇠). 비우면 서명 검증만 수행.
    SES_SNS_TOPIC_ARN: str = ""
    # 수신거부 링크·본문 링크의 공개 웹 기준 URL
    PUBLIC_WEB_URL: str = "https://bideasy.kr"
    PUBLIC_API_URL: str = "https://api.bideasy.kr"

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
