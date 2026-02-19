"""
Bid Easy API Server
- 낙찰률 예측 API
- 나라장터 데이터 조회 API
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# API 라우터 임포트
from app.api.routes.prediction import router as prediction_router
from app.api.routes.simulation import router as simulation_router

# FastAPI 앱 생성
app = FastAPI(
    title="Bid Easy API",
    description="나라장터 낙찰률 예측 서비스",
    version="1.0.0",
)

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 라우터 등록
app.include_router(prediction_router, prefix="/api")
app.include_router(simulation_router, prefix="/api")


@app.get("/")
async def root():
    """API 루트"""
    return {
        "name": "Bid Easy API",
        "version": "1.0.0",
        "status": "running",
        "endpoints": {
            "predict": "/api/predict/bid-rate",
            "statistics": "/api/predict/statistics",
            "health": "/api/predict/health",
            "docs": "/docs"
        }
    }


@app.get("/health")
async def health():
    """서버 헬스체크"""
    return {"status": "healthy"}
