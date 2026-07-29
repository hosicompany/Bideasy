"""웹 미러(assets/lower-limits.js) ↔ 백엔드 정본(lower_limits.py) 드리프트 가드.

2026-07-23 배경: PR #26 이 백엔드 하한율을 금액대 티어로 통합했지만 정적 웹
계산기·랜딩의 클라이언트 하드코딩(87.745 고정)이 누락돼, 5억 공사 88.20% 투찰에
'안전선 통과'를 띄우는 안전 버그가 실서비스에 노출됐다. 이 테스트는 JS 미러가
정본 테이블과 어긋나면 CI 에서 즉시 실패시킨다.
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from app.services.lower_limits import get_lower_limit_rate

_JS_PATH = (
    Path(__file__).resolve().parents[2]
    / "infra" / "nginx" / "html" / "assets" / "lower-limits.js"
)

# 대표 금액 → 정본 기대값 (2026 테이블, 오늘 날짜 기준)
_SAMPLES = {
    50_000_000: 89.745,        # 3억 미만
    500_000_000: 89.745,       # 3억~10억
    1_500_000_000: 88.745,     # 10억~50억
    7_000_000_000: 87.495,     # 50억 이상
    20_000_000_000: 87.495,    # 100억 이상 (동일 티어)
}


def _js_construction_rate(js_src: str, basic_price: float) -> float:
    """JS construction() 의 임계·반환값을 파싱해 파이썬으로 동일 판정을 재현."""
    pairs = re.findall(r"if \(basicPrice >= (\d+)\) return ([\d.]+);", js_src)
    assert pairs, "lower-limits.js 에서 티어 구문을 찾지 못했어요 — 구조 변경 시 테스트도 갱신 필요"
    default = re.search(r"return ([\d.]+);\s+// 10억 미만", js_src)
    assert default, "lower-limits.js 기본(10억 미만) 반환값을 찾지 못했어요"
    for threshold, rate in pairs:
        if basic_price >= int(threshold):
            return float(rate)
    return float(default.group(1))


class TestLowerLimitsWebSync:
    def test_js_mirror_exists(self):
        assert _JS_PATH.exists(), f"웹 미러 파일이 없어요: {_JS_PATH}"

    def test_construction_tiers_match_backend(self):
        js = _JS_PATH.read_text(encoding="utf-8")
        today = date.today()
        assert today >= date(2026, 1, 30), "2026 개정 이후에만 유효한 테스트"
        for price, expected in _SAMPLES.items():
            backend = get_lower_limit_rate("CONSTRUCTION", price)
            web = _js_construction_rate(js, price)
            assert backend == expected, f"백엔드 정본 회귀: {price} → {backend} (기대 {expected})"
            assert web == backend, (
                f"JS 미러 드리프트: 기초금액 {price:,} 에서 웹 {web} ≠ 백엔드 {backend} — "
                "lower_limits.py 와 lower-limits.js 를 함께 수정하세요."
            )

    def test_web_pages_do_not_hardcode_construction_rate(self):
        """계산기·랜딩이 공사 하한율을 다시 하드코딩하면 실패 (재발 방지)."""
        html_dir = _JS_PATH.parents[1]
        for name in ("calculator.html", "index.html"):
            src = (html_dir / name).read_text(encoding="utf-8")
            assert "BD_LOWER.construction" in src, f"{name} 이 티어 함수를 쓰지 않아요"
            # JS 코드 라인에 87.745 상수가 CONSTRUCTION 키로 재등장하는지 검사
            assert not re.search(r"CONSTRUCTION\s*:\s*87\.745", src), (
                f"{name} 에 공사 하한율 87.745 하드코딩이 재도입됐어요 — BD_LOWER.construction() 사용"
            )
