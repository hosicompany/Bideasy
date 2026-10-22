"""홈(/)과 /calculator 가 같은 계산기 마크업을 갖는지 — 로직(assets/calc.js)은 하나, 마크업은 두 곳.

calc.js 가 찾는 id 가 한쪽에서 빠지면 그 페이지 계산기가 조용히 멈춘다.
"""
import re
from pathlib import Path

_HTML = Path(__file__).resolve().parents[2] / "infra" / "nginx" / "html"
_CALC_JS = _HTML / "assets" / "calc.js"


def _ids_used_by_calc_js() -> set[str]:
    js = _CALC_JS.read_text(encoding="utf-8")
    return set(re.findall(r"getElementById\('([a-z-]+)'\)", js))


def test_calc_js_ids_exist_on_both_pages():
    ids = (_ids_used_by_calc_js() | {"seg"}) - {"from-bid-link", "copy", "share"}  # seg 는 querySelectorAll, 나머지는 선택·동적 요소
    assert {"basic", "tcl", "aval", "result"} <= ids
    for page in ("calculator.html", "index.html"):
        src = (_HTML / page).read_text(encoding="utf-8")
        missing = sorted(i for i in ids if f'id="{i}"' not in src)
        assert not missing, f"{page} 에 계산기 요소가 없어요: {missing}"


def test_home_has_no_paid_entry_points():
    """유료 모델 잠정 중단(2026-10) — 홈에 체험·요금제·가입 유도가 다시 들어오면 실패."""
    src = (_HTML / "index.html").read_text(encoding="utf-8")
    for word in ("14일", "요금제</a>", "/pricing", "/signup", "Pro+", "잠금 해제", "무료 체험"):
        assert word not in src, f"홈에 유료 유도 '{word}' 가 있어요"


def test_home_ad_slots_stay_hidden_until_adsense():
    src = (_HTML / "index.html").read_text(encoding="utf-8")
    slots = re.findall(r'<div class="ad-slot"[^>]*>', src)
    assert slots and all(" hidden" in s for s in slots)


def test_adsense_ownership_without_ad_script():
    """애드센스 소유권 확인은 메타 태그 + ads.txt 로만 — 승인·배치 결정 전엔 광고 스크립트를 넣지 않는다."""
    meta = '<meta name="google-adsense-account" content="ca-pub-6337758470578530">'
    tpl = _HTML.parents[2] / "backend" / "templates"
    for page in (_HTML / "index.html", _HTML / "calculator.html", tpl / "blog_detail.html",
                 tpl / "lower_limits.html", tpl / "bid_detail.html"):
        src = page.read_text(encoding="utf-8")
        assert meta in src, f"{page.name} 에 애드센스 메타 태그 없음"
        assert "adsbygoogle" not in src, f"{page.name} 에 광고 스크립트가 들어감 — 승인 후 별도 결정"
    assert (_HTML / "ads.txt").read_text().strip() == "google.com, pub-6337758470578530, DIRECT, f08c47fec0942fa0"


def test_mock_band_shows_volume_not_performance():
    """띠(B2)는 '매일 검증 중' 운영량만 — 계산기 성적처럼 읽히는 문구·무효/유효율 수치는 홈에 쓰지 않는다."""
    src = (_HTML / "index.html").read_text(encoding="utf-8")
    assert "BidEasy는 매일 실제 개찰 결과로 검증해요" in src
    for banned in ("이 계산 로직으로", "mock-dropout", "mock-valid", "유효율"):
        assert banned not in src, f"홈 띠에 성적 표기 재유입: {banned}"
