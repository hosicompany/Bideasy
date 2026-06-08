from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.core.logging import setup_logging
from app.core.rate_limit import limiter
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from app.api.v1.api import api_router
from app.api.v1.endpoints.health import router as health_router
from app.db.base import Base
from app.db.session import engine

setup_logging()

# Sentry error tracking (only when DSN is configured)
if settings.SENTRY_DSN and settings.SENTRY_DSN.strip().startswith("https://"):
    import sentry_sdk
    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        environment=settings.APP_ENV,
        release=f"bideasy-backend@{settings.PROJECT_VERSION}",
        traces_sample_rate=0.1 if settings.APP_ENV == "production" else 1.0,
        profiles_sample_rate=0.1 if settings.APP_ENV == "production" else 0,
        send_default_pii=False,
    )

# Production: trust X-Forwarded-For from Nginx reverse proxy
if settings.APP_ENV == "production":
    from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

# SQLite 개발 모드에서만 자동 테이블 생성 (PostgreSQL은 Alembic 마이그레이션 사용)
if settings.DATABASE_MODE == "sqlite":
    Base.metadata.create_all(bind=engine)

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.PROJECT_VERSION,
    description="BidEasy Backend API",
    docs_url="/docs" if settings.APP_ENV == "development" else None,
    redoc_url=None,
)

if settings.APP_ENV == "production":
    app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=["*"])

# Rate Limiting
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS: Development allows all localhost origins + Chrome extensions; production uses explicit list
if settings.APP_ENV == "development":
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"^(https?://(localhost|127\.0\.0\.1)(:\d+)?|chrome-extension://[a-z]{32})$",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
else:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.BACKEND_CORS_ORIGINS,
        allow_origin_regex=r"^chrome-extension://[a-z]{32}$",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(health_router, tags=["health"])
app.include_router(api_router, prefix=settings.API_V1_STR)

# 공개 SEO 페이지 (SSR) — /bid/{no}, /sitemap.xml, /robots.txt (root, no /api prefix)
from app.api.v1.endpoints.pages import router as pages_router  # noqa: E402
app.include_router(pages_router, tags=["pages"])

@app.get("/")
async def root():
    return {"message": f"Welcome to {settings.PROJECT_NAME} API"}

