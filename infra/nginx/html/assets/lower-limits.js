/* 낙찰하한율 — 시설공사 금액대별 티어 (2026-01-30 시행 개정)
 * ★ KEEP IN SYNC: 정본은 backend/app/services/lower_limits.py (_CONSTRUCTION_2026, lower_limit_from_basis).
 *   백엔드 테이블이 바뀌면 이 파일도 함께 수정할 것 — backend/tests/test_lower_limits_sync.py 가 드리프트를 감시한다.
 * 금액대 경계는 **추정가격**(부가세 제외) 기준이다. 웹 화면은 대부분 기초금액을 받으므로 fromBasis() 를 쓴다.
 * 클라이언트는 항상 오늘 날짜 기준(개정 시행 이후)이라 2026 테이블만 미러링한다.
 * 용역·물품은 계약유형별로 하한 개념이 달라 기존 페이지 정책 유지(도메인 재검토 전 변경 금지). */
window.BD_LOWER = {
  construction: function (estimatedPrice) {
    if (!estimatedPrice || estimatedPrice <= 0) return 87.745; // 금액 미상 폴백 — 정본 LEGACY_RATES 와 동일
    if (estimatedPrice >= 5000000000) return 87.495;       // 50억 이상
    if (estimatedPrice >= 1000000000) return 88.745;       // 10억 이상 50억 미만
    return 89.745;                                         // 10억 미만
  },
  // 기초금액만 알 때: 추정가격은 기초금액×10/11(과세)~기초금액(면세) 사이. (÷1.1 은 부동소수점 오차로 경계가 밀린다)
  // 두 끝의 티어가 다르면(기초금액 10억~11억 등) 높은 요율을 쓰고 ambiguous 로 알린다.
  fromBasis: function (basisAmount) {
    if (!basisAmount || basisAmount <= 0) return { rate: this.construction(0), ambiguous: false };
    var taxed = this.construction(basisAmount * 10 / 11), exempt = this.construction(basisAmount);
    return { rate: Math.max(taxed, exempt), ambiguous: taxed !== exempt };
  }
};
