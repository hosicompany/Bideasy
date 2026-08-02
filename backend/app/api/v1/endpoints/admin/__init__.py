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
- simulation : 과거 데이터 백테스트 (Phase E)
- mock_bidding : 모의투찰 사전등록·채점 조회 (docs/MOCK_BIDDING_DESIGN.md)
"""
from fastapi import APIRouter, Depends

from app.core.security import require_admin

from . import accuracy, dashboard, users, payments, autocalibrate, system, simulation, blog, leads, consents, outbound, mock_bidding

# 라우터 수준 의존성 — 모든 sub-router 가 자동으로 require_admin 거침.
# 개별 엔드포인트의 _admin=Depends(require_admin) 는 명시성·테스트 가독성 위해 유지.
router = APIRouter(dependencies=[Depends(require_admin)])
router.include_router(accuracy.router)
router.include_router(dashboard.router)
router.include_router(users.router)
router.include_router(payments.router)
router.include_router(autocalibrate.router)  # Phase D — 자가보정 운영
router.include_router(system.router)          # Phase D — 시스템 수동 트리거
router.include_router(simulation.router)      # Phase E — 모의 투찰 백테스트
router.include_router(blog.router)            # 블로그 — DB 기반 런타임 발행
router.include_router(leads.router)           # 리드 획득·전환 대시보드
router.include_router(consents.router)        # 수신동의 증적 조회(발송 적법성 근거)
router.include_router(outbound.router)        # 아웃바운드 발송 원장·미리보기·테스트
router.include_router(mock_bidding.router)    # 모의투찰 — 사전등록·채점 조회
