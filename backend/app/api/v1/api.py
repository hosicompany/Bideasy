from fastapi import APIRouter
from app.api.v1.endpoints import bids, ai, users, prediction

api_router = APIRouter()
api_router.include_router(bids.router, prefix="/bids", tags=["bids"])
api_router.include_router(ai.router, prefix="/ai", tags=["ai"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(prediction.router, prefix="/analysis", tags=["analysis"])
