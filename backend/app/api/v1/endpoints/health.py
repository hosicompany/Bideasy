from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.config import settings

router = APIRouter()


@router.get("/health")
def health_check(db: Session = Depends(get_db)):
    status = {"status": "ok", "version": settings.PROJECT_VERSION}

    # DB check
    try:
        db.execute(text("SELECT 1"))
        status["database"] = "connected"
    except Exception:
        status["database"] = "error"
        status["status"] = "degraded"

    # Redis check (optional)
    try:
        import redis
        r = redis.from_url(settings.redis_url, socket_connect_timeout=1)
        r.ping()
        status["redis"] = "connected"
    except Exception:
        status["redis"] = "unavailable"

    # ML models check
    import os
    models_path = settings.ML_MODELS_PATH
    ml_files = [f for f in os.listdir(models_path) if f.endswith(".joblib")] if os.path.isdir(models_path) else []
    status["ml_models"] = len(ml_files)

    return status
