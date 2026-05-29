"""
관리자 API 패키지
==================
모든 /api/v1/admin/* 라우트는 `require_admin` 의존성 가드를 거쳐야 한다.
누락 방지: `tests/test_admin_auth.py::test_all_admin_routes_have_guard` 자동 회귀.

서브 라우터:
- accuracy   : 기존 자가보정 정확도 통계 (3개 GET)
- dashboard  : 모니터링 KPI (Phase B 에서 추가)
- users      : 사용자 관리 (Phase C)
- payments   : 결제·환불 관리 (Phase C)
- autocalibrate : 자가보정 운영 (Phase D)
- system     : 수동 트리거·헬스 (Phase D)
- simulation : 모의 투찰 백테스트 (Phase E)
"""
from fastapi import APIRouter, Depends

from app.core.security import require_admin

from . import accuracy, dashboard

# 라우터 수준 의존성 — 모든 sub-router 가 자동으로 require_admin 거침.
# 개별 엔드포인트의 _admin=Depends(require_admin) 는 명시성·테스트 가독성 위해 유지.
router = APIRouter(dependencies=[Depends(require_admin)])
router.include_router(accuracy.router)
router.include_router(dashboard.router)

# Phase C 이후 sub-router 추가:
# from . import users, payments, autocalibrate, system, simulation
# router.include_router(users.router)
# ...
