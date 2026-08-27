"""투찰 근거서(rationale.html) 카피 규칙 가드.

2026-08-27 배경: 디자인 핸드오프 명세가 금지 어휘를 **기능 요구사항**으로 규정했다.
이 시장의 실무자는 "적중률 85%" 같은 주장을 예정가격 변동 폭(±2~3%)을 근거로 즉시
논파하고 사기로 분류한다. 문구 취향이 아니라 제품 요구사항이므로 CI 에서 강제한다.

규칙(`docs/design/design_handoff_bid_rationale/README.md`):
- 금지어를 **긍정문**으로 쓸 수 없다. 부정문("예측하지 않았습니다")은 허용·권장.
- `안전`은 부정문으로도 쓰지 않는다 — 실무자 발화 8,252건에서 0회 등장한 언어다.
- 낙찰하한율은 하드코딩하지 않고 정본 미러(assets/lower-limits.js)에서 가져온다.
"""

from __future__ import annotations

import re
from pathlib import Path

_HTML_PATH = (
    Path(__file__).resolve().parents[2] / "infra" / "nginx" / "html" / "rationale.html"
)

# 부정문으로만 등장해야 하는 어휘
_BANNED_UNLESS_NEGATED = ["적중", "예측", "낙찰 확률", "낙찰률", "보장", "성공", "추천가"]
# 부정문으로도 쓰지 않는 어휘
_BANNED_ALWAYS = ["안전"]

# 단, 법정 비목·제도 명칭에 포함된 '안전'은 예외다. 금지 규칙의 대상은
# "안전 투찰" 같은 마케팅 프레임이지 법령이 정한 항목 이름이 아니다.
_LEGAL_TERMS = ("산업안전보건관리비", "안전관리비", "안전점검비", "중대재해")

# 금지어 뒤 14자 안에 이런 표현이 있으면 부정문으로 본다.
_NEGATION = re.compile(r"(하지 않|않습니다|않았습니다|없|못|아닙니다|아님)")


def _document_text() -> str:
    """주석·스타일을 걷어낸, 사용자에게 보이는 문자열만 남긴다."""
    raw = _HTML_PATH.read_text(encoding="utf-8")
    raw = re.sub(r"<!--.*?-->", " ", raw, flags=re.S)
    raw = re.sub(r"<style.*?</style>", " ", raw, flags=re.S)
    # JS 주석도 카피가 아니다
    raw = re.sub(r"/\*.*?\*/", " ", raw, flags=re.S)
    raw = re.sub(r"//[^\n]*", " ", raw)
    return raw


def test_banned_terms_appear_only_in_negated_form():
    text = _document_text()
    violations = []
    for word in _BANNED_UNLESS_NEGATED:
        for m in re.finditer(re.escape(word), text):
            window = text[m.start() : m.end() + 14]
            if not _NEGATION.search(window):
                ctx = text[max(0, m.start() - 20) : m.end() + 20].replace("\n", " ")
                violations.append(f"{word!r} 가 긍정문으로 쓰였습니다: …{ctx.strip()}…")
    assert not violations, "금지 어휘 위반:\n" + "\n".join(violations)


def test_safety_word_never_used():
    text = _document_text()
    hits = []
    for word in _BANNED_ALWAYS:
        for m in re.finditer(re.escape(word), text):
            window = text[max(0, m.start() - 10) : m.end() + 12]
            if any(t in window for t in _LEGAL_TERMS):
                continue  # 법정 비목명 안의 '안전'
            hits.append(text[max(0, m.start() - 20) : m.end() + 20].replace("\n", " "))
    assert not hits, "'안전'은 부정문으로도 쓰지 않는다:\n" + "\n".join(hits)


def test_required_disclaimers_present():
    """대표가 '그래서 딸 수 있어?'라고 물을 때 문서가 이미 답하고 있어야 한다."""
    text = _document_text()
    for phrase in (
        "낙찰가를 예측하지 않았습니다",
        "낙찰 가능성이나 순위를 계산하지 않았습니다",
        "낙찰 결과를 보장하지 않습니다",
    ):
        assert phrase in text, f"필수 부인 문구 누락: {phrase}"

    # 낙찰하한선은 법정 최저 기준이며 원가선이 아니다 — 산출표와 4번 섹션에서 각각 1회
    assert text.count("원가선이 아님") + text.count("원가선이 아닙니다") >= 2, (
        "'하한선은 원가선이 아니다' 부인이 두 곳(산출표·4번 섹션)에 있어야 합니다"
    )


def test_lower_limit_rate_is_not_hardcoded():
    """하한율은 정본 미러에서 가져온다 — 하드코딩하면 개정 때 조용히 어긋난다."""
    raw = _HTML_PATH.read_text(encoding="utf-8")
    assert "BD_LOWER.construction" in raw, (
        "낙찰하한율은 assets/lower-limits.js(정본 미러)에서 가져와야 합니다"
    )
    # 하한율 상수를 직접 박아두지 않았는지 (JS 리터럴로 등장하면 드리프트 위험)
    for literal in ("0.88745", "0.89745", "0.87495"):
        assert literal not in raw, f"하한율 {literal} 이 하드코딩돼 있습니다"
