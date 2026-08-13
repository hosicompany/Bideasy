from fastapi import APIRouter
from app.api.v1.endpoints import (
    admin,
    agency,
    ai,
    analysis,
    auth,
    autocalibrate,
    bids,
    creative_runner,
    growth,
    leads,
    message_validation,
    notifications,
    optin,
    payments,
    points,
    prediction,
    recommendation_events,
    smart_bid,
    support,
    unsubscribe,
    users,
    webhooks_ses,
)

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
api_router.include_router(
    recommendation_events.router,
    prefix="/recommendations",
    tags=["recommendation-events"],
)
api_router.include_router(notifications.router, prefix="/notifications", tags=["notifications"])
api_router.include_router(admin.router, prefix="/admin", tags=["admin"])
api_router.include_router(autocalibrate.router, prefix="/autocalibrate", tags=["autocalibrate"])
api_router.include_router(support.router, prefix="/support", tags=["support"])
api_router.include_router(leads.router, prefix="/leads", tags=["leads"])
api_router.include_router(growth.router, prefix="/growth", tags=["growth"])
api_router.include_router(message_validation.router, prefix="/message-test", tags=["message-test"])
# 인증된 운영자 Mac의 Higgsfield runner 전용(일반 JWT·admin 토큰 미사용).
api_router.include_router(
    creative_runner.router,
    prefix="/creative-runner",
    tags=["creative-runner"],
)
# 수신거부는 공개·무인증(메일 링크에서 바로 도달). prefix 없이 /unsubscribe 로 노출.
api_router.include_router(unsubscribe.router, tags=["unsubscribe"])
# 더블 옵트인 확인도 공개·무인증(메일 링크에서 바로 도달). 리드·회원 공용이라 prefix 없음.
api_router.include_router(optin.router, tags=["optin"])
# SES 반송·불만 웹훅(SNS). 무인증 — 진위는 AWS 서명 검증으로 판정한다.
api_router.include_router(webhooks_ses.router, tags=["webhooks"])
