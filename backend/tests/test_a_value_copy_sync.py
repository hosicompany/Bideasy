"""A값 설명 문구 ↔ 정본(A_VALUE_KEYS) 드리프트 가드.

2026-08-27 배경: A값을 "국민연금·건강보험·**산재·고용**·노인장기요양" 5종으로 설명하는
문구가 **9곳**(랜딩 FAQ·JSON-LD·가이드·계산기·카드메이커·관리자 용어집·챗봇 프롬프트·
블로그 생성 프롬프트·스크레이퍼 주석)에 흩어져 있었고 전부 틀렸다.

실제 구성은 `basis_amount_crawler.A_VALUE_KEYS` 10종이며 **산재·고용보험은 포함되지
않는다**(퇴직공제부금비·산업안전보건관리비·품질관리비·환경보전비 등이 들어간다).
2026-08-08 기초금액 tier0 수집을 붙이며 실제 API 응답으로 확인된 사실인데, 고객
대면 문구가 따라오지 않아 라이브 FAQ 가 구조화 데이터로 오정보를 내보내고 있었다.

같은 값이 여러 곳에 복사돼 있는 한 또 어긋난다 — 이 테스트가 드리프트를 막는다.
(같은 취지의 선례: tests/test_lower_limits_sync.py)
"""

from __future__ import annotations

import re
from pathlib import Path

from app.services.basis_amount_crawler import A_VALUE_KEYS

_ROOT = Path(__file__).resolve().parents[2]

# A값을 설명하는 고객 대면·내부 표면 전부
_SURFACES = [
    "infra/nginx/html/index.html",
    "infra/nginx/html/calculator.html",
    "infra/nginx/html/guide.html",
    "infra/nginx/html/cardmaker.html",
    "infra/nginx/html/admin/admin.js",
    "backend/app/api/v1/endpoints/support.py",
    "backend/app/services/content_engine.py",
    "backend/app/services/scraper.py",
    "infra/nginx/html/rationale.html",
]

# "산재·고용" 이 부정문(포함되지 않는다/제외/들어가지 않는다)으로 쓰였으면 통과
_NEGATED = re.compile(r"산재·고용[^\n]{0,40}?(포함되지 않|제외|들어가지 않|아닙니다)")


def test_a_value_has_ten_components():
    """정본이 10종이라는 전제가 깨지면 문구도 전부 다시 봐야 한다."""
    assert len(A_VALUE_KEYS) == 10, (
        f"A_VALUE_KEYS 가 {len(A_VALUE_KEYS)}종으로 바뀌었습니다. "
        "고객 대면 '10종' 표기를 함께 수정하세요: " + ", ".join(_SURFACES)
    )


def test_no_surface_claims_industrial_accident_or_employment_insurance():
    """산재·고용보험은 A값 구성에 없다 — 긍정문으로 쓰면 오정보다."""
    violations = []
    for rel in _SURFACES:
        path = _ROOT / rel
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        for m in re.finditer(r"산재·고용", text):
            window = text[m.start() : m.end() + 40]
            if _NEGATED.search(text[m.start() : m.end() + 40]) or _NEGATED.search(window):
                continue
            line = text[: m.start()].count("\n") + 1
            violations.append(f"{rel}:{line} — {window.splitlines()[0][:70]}")
    assert not violations, (
        "A값 구성에 산재·고용보험이 포함된 것처럼 쓰인 곳:\n" + "\n".join(violations)
    )


def test_a_value_source_of_truth_is_referenced():
    """정본 위치를 코드 주석이 가리키게 해 다음 사람이 복사본을 또 만들지 않게 한다."""
    scraper = (_ROOT / "backend/app/services/scraper.py").read_text(encoding="utf-8")
    assert "A_VALUE_KEYS" in scraper, (
        "scraper.py 의 A값 주석이 정본(basis_amount_crawler.A_VALUE_KEYS)을 가리켜야 합니다"
    )
