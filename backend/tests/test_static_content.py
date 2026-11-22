"""공개 정적 페이지의 본문이 첫 HTML 에 있는지 — 애드센스 재검토(2026-11) 회귀 가드.

약관·가이드·홈 FAQ 본문이 JS(innerHTML)로만 그려져 크롤러에게 빈 문서로 보였다.
본문을 HTML 로 옮겼으니 다시 JS 로 돌아가거나, 공통 푸터가 페이지마다 갈라지면 실패한다.
"""
import html
import json
import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_HTML = _ROOT / "infra" / "nginx" / "html"
_TPL = _ROOT / "backend" / "templates"
_FOOTER = (_TPL / "_site_footer.html").read_text(encoding="utf-8").rstrip("\n")

# 페이지 → JS 없이 보여야 하는 본문 한글 최소 글자 수(메뉴·푸터 제외)
_MIN_HANGUL = {
    "terms.html": 900,
    "guide.html": 1200,
    "calculator.html": 1800,
    "about.html": 1200,
    "contact.html": 600,
    "start-guide.html": 3000,
    "calculator-examples.html": 2500,
    "faq.html": 2500,
    "extension.html": 1800,
}


def _body_text(src: str) -> str:
    src = re.sub(r"(?is)<(script|style|noscript|nav|footer|head)\b.*?</\1>", " ", src)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"(?s)<[^>]+>", " ", src))).strip()


def _hangul(text: str) -> int:
    return len(re.findall(r"[가-힣]", text))


@pytest.mark.parametrize("page,minimum", sorted(_MIN_HANGUL.items()))
def test_page_body_is_in_first_html(page, minimum):
    src = (_HTML / page).read_text(encoding="utf-8")
    assert "innerHTML" not in src, f"{page}: 본문을 JS 로 그리면 크롤러에게 빈 문서로 보여요"
    assert _hangul(_body_text(src)) >= minimum, f"{page}: JS 없이 보이는 본문이 {minimum}자 미만"


@pytest.mark.parametrize("page", sorted(_MIN_HANGUL) + ["diagnose.html"])
def test_static_pages_share_footer_and_meta(page):
    src = (_HTML / page).read_text(encoding="utf-8")
    assert _FOOTER in src, f"{page}: 공통 푸터가 _site_footer.html 과 다릅니다(복사본 갱신 필요)"
    assert '<link rel="canonical" href="https://bideasy.kr/' in src
    assert "adsbygoogle" not in src
    assert "낙찰률" not in src


@pytest.mark.parametrize("tpl", ["lower_limits.html", "a_value.html"])
def test_reference_templates_include_footer(tpl):
    assert '{% include "_site_footer.html" %}' in (_TPL / tpl).read_text(encoding="utf-8")


def test_home_faq_html_matches_json_ld():
    """홈 FAQ 는 HTML 에 직접 있고, FAQPage JSON-LD 와 문구가 같다(구조화 데이터 = 보이는 본문)."""
    src = (_HTML / "index.html").read_text(encoding="utf-8")
    ld = next(
        json.loads(block)
        for block in re.findall(r'<script type="application/ld\+json">(.*?)</script>', src, re.S)
        if '"FAQPage"' in block
    )
    faq = src[src.index('id="faq">'):]
    plain = lambda h: html.unescape(re.sub(r"<[^>]+>", "", h)).strip()  # noqa: E731
    shown = [(plain(q), plain(a)) for q, a in re.findall(
        r'<details><summary>(.*?)</summary><div class="fa">(.*?)</div></details>', faq)]
    expected = [(e["name"], e["acceptedAnswer"]["text"]) for e in ld["mainEntity"]]
    assert shown == expected
