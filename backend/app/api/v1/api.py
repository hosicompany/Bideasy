from fastapi import APIRouter
from app.api.v1.endpoints import bids, ai, users, prediction, analysis, auth, points, agency

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(bids.router, prefix="/bids", tags=["bids"])
api_router.include_router(ai.router, prefix="/ai", tags=["ai"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(points.router, prefix="/points", tags=["points"])
api_router.include_router(prediction.router, prefix="/prediction", tags=["prediction"])
api_router.include_router(analysis.router, prefix="/analysis", tags=["analysis"])
api_router.include_router(agency.router, prefix="/agency", tags=["agency"])
