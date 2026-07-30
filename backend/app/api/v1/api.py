from fastapi import APIRouter
from app.api.v1.endpoints import bids, ai, users, prediction, analysis, auth, points, payments, agency, smart_bid, notifications, admin, autocalibrate, support, leads, unsubscribe, webhooks_ses

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(bids.router, prefix="/bids", tags=["bids"])
api_router.include_router(ai.router, prefix="/ai", tags=["ai"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(points.router, prefix="/points", tags=["points"])
api_router.include_router(payments.router, prefix="/payments", tags=["payments"])
api_router.include_router(prediction.router, prefix="/prediction", tags=["prediction"])
api_router.include_router(analysis.router, prefix="/analysis", tags=["analysis"])
api_router.include_router(agency.router, prefix="/agency", tags=["agency"])
api_router.include_router(smart_bid.router, prefix="/smart-bid", tags=["smart-bid"])
api_router.include_router(notifications.router, prefix="/notifications", tags=["notifications"])
api_router.include_router(admin.router, prefix="/admin", tags=["admin"])
api_router.include_router(autocalibrate.router, prefix="/autocalibrate", tags=["autocalibrate"])
api_router.include_router(support.router, prefix="/support", tags=["support"])
api_router.include_router(leads.router, prefix="/leads", tags=["leads"])
# 수신거부는 공개·무인증(메일 링크에서 바로 도달). prefix 없이 /unsubscribe 로 노출.
api_router.include_router(unsubscribe.router, tags=["unsubscribe"])
# SES 반송·불만 웹훅(SNS). 무인증 — 진위는 AWS 서명 검증으로 판정한다.
api_router.include_router(webhooks_ses.router, tags=["webhooks"])
