"""기초금액 판정 단일 소스 (`services/basis.py`) 테스트.

지키려는 계약 두 가지 (docs/PRICE_BASE_DEFECT.md 2층-B):
1. **추정하지 않는다** — 기초금액이 없으면 None. `basic_price × 1.1` 금지
   (실측 비율이 0.9877~1.1223 로 흩어진다).
2. **없으면 안전 판정을 보류한다** — 하한선을 못 구하니 "안전"도 "위험"도
   말할 수 없다.

그리고 시행 스위치(BASIS_AMOUNT_ENFORCE)가 OFF 인 동안에는 기존 동작이
그대로여야 한다 — 배포와 시행을 분리하기 위함이다.
"""
import pytest

from app.db import models
from app.services import basis


@pytest.fixture
def enforce(monkeypatch):
    monkeypatch.setattr(basis.settings, "BASIS_AMOUNT_ENFORCE", True, raising=False)


def _notice(basic=100_000_000.0, basis_amount=None):
    n = models.Notice(bid_no="T-1", title="t", basic_price=basic,
                      contract_type="CONSTRUCTION")
    n.basis_amount = basis_amount
    return n


class TestBeforeEnforcement:
    """시행 전에는 동작이 바뀌지 않는다 — 배포해도 안전하다."""

    def test_status_is_legacy(self):
        assert basis.basis_status(_notice()) == basis.LEGACY

    def test_falls_back_to_basic_price(self):
        assert basis.confirmed_basis(_notice(basic=100_000_000.0)) == 100_000_000.0

    def test_display_shows_basic_price(self):
        amount, st = basis.display_basis(_notice(basic=123.0))
        assert amount == 123 and st == basis.LEGACY


class TestAfterEnforcement:
    def test_confirmed_when_basis_amount_present(self, enforce):
        n = _notice(basic=100_000_000.0, basis_amount=110_000_000.0)
        assert basis.basis_status(n) == basis.CONFIRMED
        assert basis.confirmed_basis(n) == 110_000_000.0

    def test_unconfirmed_returns_none(self, enforce):
        """⛔ basic_price 로 폴백하면 안 된다 — 그게 이번 사고의 원인이다."""
        n = _notice(basic=100_000_000.0, basis_amount=None)
        assert basis.basis_status(n) == basis.UNCONFIRMED
        assert basis.confirmed_basis(n) is None

    def test_never_estimates_by_multiplying(self, enforce):
        """×1.1 같은 보정을 하지 않는다 (실측 비율 0.9877~1.1223)."""
        n = _notice(basic=100_000_000.0, basis_amount=None)
        got = basis.confirmed_basis(n)
        assert got is None
        assert got != pytest.approx(110_000_000.0)

    def test_display_hides_amount_when_unconfirmed(self, enforce):
        """틀린 숫자를 보여주느니 아무것도 보여주지 않는다."""
        amount, st = basis.display_basis(_notice(basis_amount=None))
        assert amount == 0 and st == basis.UNCONFIRMED

    def test_zero_basis_amount_is_unconfirmed(self, enforce):
        assert basis.basis_status(_notice(basis_amount=0)) == basis.UNCONFIRMED

    def test_none_notice_is_unconfirmed(self, enforce):
        assert basis.basis_status(None) == basis.UNCONFIRMED
        assert basis.confirmed_basis(None) is None


class TestMockBiddingIntegration:
    def test_unconfirmed_notice_is_not_registered(self, enforce):
        """틀린 기준으로 등록하면 표본이 오염된다 — 많아도 쓸모가 없다."""
        from app.services import mock_bidding as mb

        n = _notice(basic=100_000_000.0, basis_amount=None)
        n.end_date = mb.now_kst()
        n.bid_method = "적격심사제"
        ok, reason = mb.is_eligible(n)
        assert ok is False and reason == "no_basis_amount"

    def test_prices_use_basis_amount_not_basic_price(self, enforce):
        """등록가는 기초금액 기준이어야 한다."""
        from app.services import mock_bidding as mb

        n = _notice(basic=100_000_000.0, basis_amount=110_000_000.0)
        n.bid_method = "적격심사제"
        prices = mb.compute_arm_prices(n)
        std = next(p for p in prices if p.arm == "standard")
        # standard = 기초금액 × 97.5%
        assert std.price == pytest.approx(110_000_000 * 0.975, rel=1e-6)


class TestNoticeDetailPage:
    """공고상세 SSR — 미확인이면 금액·하한율을 보여주지 않고 계산기도 비운다."""

    def _seed(self, db_session, bid_no, basis_amount):
        from datetime import datetime, timedelta

        n = models.Notice(
            bid_no=bid_no, title="테스트공사", content="",
            basic_price=100_000_000.0, contract_type="CONSTRUCTION",
            start_date=datetime.now(), end_date=datetime.now() + timedelta(days=3),
            organization="A기관", bid_method="적격심사제",
        )
        n.basis_amount = basis_amount
        db_session.add(n)
        db_session.flush()
        return n

    def test_unconfirmed_page_withholds_numbers(self, client, db_session, enforce):
        self._seed(db_session, "PAGE-UNC-1", None)
        html = client.get("/bid/PAGE-UNC-1").text

        assert "기초금액 미확인" in html
        assert "안전 여부를 판단해 드리지 않습니다" in html
        # 추정가격이 화면·계산기 어디에도 새어 나오면 안 된다
        assert "100,000,000원" not in html
        assert 'id="calc-basic" value=""' in html.replace("\n", " ")

    def test_confirmed_page_shows_numbers(self, client, db_session, enforce):
        self._seed(db_session, "PAGE-CONF-1", 110_000_000.0)
        html = client.get("/bid/PAGE-CONF-1").text

        assert "기초금액 미확인" not in html
        assert "110,000,000원" in html
