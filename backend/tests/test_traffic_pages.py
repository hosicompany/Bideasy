"""트래픽 패키지 ①③ — 하한율표·A값 참고 페이지, 계산 결과 공유 카드."""
import pytest

from app.db import models
from app.services import a_value_stats, share_card
from app.services.lower_limits import construction_rate_table, get_lower_limit_rate


def test_lower_limits_page_renders_rates_from_source_table(client):
    resp = client.get("/lower-limits")
    assert resp.status_code == 200
    html = resp.text
    for row in construction_rate_table():
        assert f"{row['rate']:.3f}%" in html
        assert f"{row['rate_old']:.3f}%" in html
    assert 'rel="canonical" href="https://bideasy.kr/lower-limits"' in html
    assert "낙찰률" not in html


def test_rate_table_bands_follow_source_thresholds():
    rows = construction_rate_table()
    assert len(rows) == 5
    for r in rows:
        probe = max(r["threshold"], 1)
        assert get_lower_limit_rate("CONSTRUCTION", probe) == r["rate"]


def test_a_value_page_shows_band_medians_and_fill_link(client, db_session):
    a_value_stats._cache["data"] = None
    for i, (basis, a) in enumerate([(500_000_000, 10_000_000), (600_000_000, 14_000_000),
                                    (400_000_000, 12_000_000), (500_000_000, 600_000_000)]):
        db_session.add(models.Notice(bid_no=f"AV-{i}", title="t", basis_amount=basis, a_value=a,
                                     a_value_source="tier0", contract_type="CONSTRUCTION"))
    db_session.add(models.Notice(bid_no="AV-T1", title="t", basis_amount=500_000_000,
                                 a_value=99_000_000, a_value_source="tier1"))
    db_session.commit()

    stats = a_value_stats.band_medians(db_session)
    band = next(b for b in stats["bands"] if b["code"] == "3E_10E")
    assert band["n"] >= 3  # a ≥ 기초금액 행·tier1 은 제외
    assert band["median_a"] is not None
    assert 300_000_000 <= band["example_basic"] < 1_000_000_000

    a_value_stats._cache["data"] = None
    html = client.get("/a-value").text
    assert "계산기에 채우기 (추정)" in html
    assert "a_src=median" in html
    assert "산재·고용보험은 들어가지 않습니다" in html


@pytest.mark.parametrize("q", [
    {"basic": "abc", "tcl": "90"},
    {"basic": "0", "tcl": "90"},
    {"basic": "500000000", "tcl": "120"},
    {"basic": "500000000", "tcl": "90", "a": "600000000"},
    {"basic": "500000000", "tcl": "90", "ct": "BAD"},
])
def test_share_rejects_bad_params(client, q):
    assert client.get("/s/calc.png", params=q).status_code == 400
    page = client.get("/s/calc", params=q, follow_redirects=False)
    assert page.status_code == 302 and page.headers["location"] == "/calculator"


def test_share_numbers_match_web_calculator_formula():
    r = share_card.compute({"ct": "CONSTRUCTION", "basic": 500_000_000, "tcl": 90.3, "a": 12_400_000})
    # calculator.html: floor(((B−A)·t + A)/10)·10 , 하한선 = round((B−A)·rate + A)
    assert r["predicted"] == 452_702_800
    assert r["rate"] == 89.745
    assert r["lower"] == 449_996_620
    assert r["level"] == "SAFE"
    assert share_card.compute({"ct": "SERVICE", "basic": 100_000_000, "tcl": 88, "a": 0})["level"] is None


def test_share_page_has_og_card_noindex_and_escapes(client):
    resp = client.get("/s/calc", params={"ct": "CONSTRUCTION", "basic": "500000000",
                                         "tcl": "90.30", "a": "12400000"})
    assert resp.status_code == 200
    html = resp.text
    assert '<meta name="robots" content="noindex">' in html
    assert 'og:image" content="https://bideasy.kr/s/calc.png?ct=CONSTRUCTION&amp;basic=500000000&amp;tcl=90.300&amp;a=12400000"' in html
    assert "452,702,800" in html and "하한선 이상" in html
    assert 'rel="canonical" href="https://bideasy.kr/calculator"' in html


def test_share_image_is_png(client):
    resp = client.get("/s/calc.png", params={"basic": "500000000", "tcl": "90.3", "a": "12400000"})
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    assert resp.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_sitemap_static_lists_reference_pages(client):
    body = client.get("/sitemap-static.xml").text
    assert "https://bideasy.kr/lower-limits" in body and "https://bideasy.kr/a-value" in body


# ── 독립 리뷰 보완 (2026-10-22) ──
@pytest.mark.parametrize("q", [{"basic": "inf", "tcl": "90"}, {"basic": "1e999", "tcl": "90"},
                               {"basic": "500000000", "tcl": "80"}])
def test_share_rejects_overflow_and_out_of_slider_range(client, q):
    assert client.get("/s/calc.png", params=q).status_code == 400


def test_share_keeps_three_decimal_rate_end_to_end(client):
    """프리셋 89.745 를 공유해도 받는 쪽이 89.75 로 반올림된 다른 숫자를 보면 안 된다."""
    r = share_card.compute(share_card.parse("CONSTRUCTION", "500000000", "89.745", "12400000"))
    html = client.get("/s/calc", params={"basic": "500000000", "tcl": "89.745", "a": "12400000"}).text
    assert "tcl=89.745" in html
    assert share_card.won(r["predicted"]) in html


def test_share_carries_estimated_a_value_flag(client):
    html = client.get("/s/calc", params={"basic": "500000000", "tcl": "90.3",
                                         "a": "11800000", "a_src": "median"}).text
    assert "a_src=median" in html and "A값(추정)" in html
    plain = client.get("/s/calc", params={"basic": "500000000", "tcl": "90.3", "a": "11800000"}).text
    assert "a_src" not in plain and "A값(추정)" not in plain


def test_lower_line_rounds_half_up_like_browser():
    # 300,010,000 × 89.745% = 269,243,974.5 → JS Math.round 는 ...975
    r = share_card.compute({"ct": "CONSTRUCTION", "basic": 300_010_000, "tcl": 90.0, "a": 0})
    assert r["lower"] == 269_243_975
