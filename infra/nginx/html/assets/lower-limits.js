/* 낙찰하한율 — 시설공사 금액대별 티어 (2026-01-30 시행 개정)
 * ★ KEEP IN SYNC: 정본은 backend/app/services/lower_limits.py (_CONSTRUCTION_2026).
 *   백엔드 테이블이 바뀌면 이 파일도 함께 수정할 것 — backend/tests/test_lower_limits_sync.py 가 드리프트를 감시한다.
 * 클라이언트는 항상 오늘 날짜 기준(개정 시행 이후)이라 2026 테이블만 미러링한다.
 * 용역·물품은 계약유형별로 하한 개념이 달라 기존 페이지 정책 유지(도메인 재검토 전 변경 금지). */
window.BD_LOWER = {
  construction: function (basicPrice) {
    if (!basicPrice || basicPrice <= 0) return 87.745; // 금액 미상 폴백 — 정본 LEGACY_RATES 와 동일
    if (basicPrice >= 5000000000) return 87.495;       // 50억 이상
    if (basicPrice >= 1000000000) return 88.745;       // 10억 이상 50억 미만
    return 89.745;                                     // 10억 미만
  }
};
