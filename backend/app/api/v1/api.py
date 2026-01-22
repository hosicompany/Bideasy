from fastapi import APIRouter
from app.api.v1.endpoints import bids, ai

api_router = APIRouter()
api_router.include_router(bids.router, prefix="/bids", tags=["bids"])
api_router.include_router(ai.router, prefix="/ai", tags=["ai"])
