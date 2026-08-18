"""기초금액 판정 단일 소스 (`services/basis.py`) 테스트.

지키려는 계약 두 가지 (docs/PRICE_BASE_DEFECT.md 2층-B):
1. **추정하지 않는다** — 기초금액이 없으면 None. `basic_price × 1.1` 금지
   (실측 비율이 0.9877~1.1223 로 흩어진다).
2. **없으면 안전 판정을 보류한다** — 하한선을 못 구하니 "안전"도 "위험"도
   말할 수 없다.

시행 스위치는 2026-08-18 부로 불변식으로 승격돼 OFF 경로가 없다 — 아래 TestNoLegacyPath 가
그것을 고정한다.
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


class TestNoLegacyPath:
    """(2026-08-18 뒤집음) 예전 TestBeforeEnforcement 는 스위치 OFF 에서 추정가격 fallback 을
    '정상' 으로 단언했다 — 그 fallback 이 곧 함정 22 의 사고 경로다. 이제 OFF 경로는 없다."""

    def test_status_is_never_legacy(self):
        assert basis.basis_status(_notice()) == basis.UNCONFIRMED

    def test_no_fallback_to_basic_price(self):
        assert basis.confirmed_basis(_notice(basic=100_000_000.0)) is None

    def test_display_hides_unconfirmed_amount(self):
        amount, st = basis.display_basis(_notice(basic=123.0))
        assert amount == 0 and st == basis.UNCONFIRMED   # 계약: 미확인이면 0 (틀린 숫자를 안 보여준다)


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


class TestOpeningAsBasisSource:
    """개찰이 끝나면 기초금액을 안다 (2026-08-06 실측: 마감 공고 4,343건).

    개찰 API 는 `bssAmt` 를 주므로, 공고 단계에서 못 구한 건도 개찰 후엔
    확정된다. 이걸 안 보면 "알면서 모른다"고 말하는 화면이 된다.
    """

    def _opening(self, basic=110_000_000.0, reserved=110_500_000.0, winner=99_000_000.0):
        return models.OpeningResult(
            bid_no="T-1", basic_price=basic, reserved_price=reserved,
            winner_price=winner, winner_rate=89.6, winner_company="가나건설",
        )

    def test_opening_confirms_basis(self, enforce):
        n = _notice(basic=100_000_000.0, basis_amount=None)
        op = self._opening()
        assert basis.basis_status(n, op) == basis.CONFIRMED
        assert basis.confirmed_basis(n, op) == 110_000_000.0

    def test_opening_wins_over_notice(self, enforce):
        """개찰 실값이 공고 단계 값보다 확실하다."""
        n = _notice(basis_amount=108_000_000.0)
        assert basis.confirmed_basis(n, self._opening()) == 110_000_000.0

    def test_inconsistent_opening_row_is_rejected(self, enforce):
        """백필 안 된 옛 행(추정가격 기준)은 쓰지 않는다 — 기준이 다시 섞인다.

        사정률 110,000,000/100,000,000 = 1.10 → 부가세 기준이 다른 행.
        """
        n = _notice(basis_amount=None)
        bad = self._opening(basic=100_000_000.0, reserved=110_000_000.0)
        assert basis.confirmed_basis(n, bad) is None
        assert basis.basis_status(n, bad) == basis.UNCONFIRMED

    def test_opening_without_reserved_is_accepted(self, enforce):
        """예정가격이 없으면 검증은 못 하지만 기초금액 자체는 쓴다."""
        n = _notice(basis_amount=None)
        op = self._opening(reserved=0)
        assert basis.confirmed_basis(n, op) == 110_000_000.0


class TestClosedNoticePage:
    """마감 후 화면은 '얼마 넣을까'가 아니라 '얼마에 됐나'를 답해야 한다."""

    def _seed(self, db_session, bid_no, *, basis_amount=None, with_result=True):
        from datetime import datetime, timedelta

        n = models.Notice(
            bid_no=bid_no, title="마감공사", content="",
            basic_price=100_000_000.0, contract_type="CONSTRUCTION",
            start_date=datetime.now() - timedelta(days=10),
            end_date=datetime.now() - timedelta(days=2),   # 이미 마감
            organization="A기관", bid_method="적격심사제",
        )
        n.basis_amount = basis_amount
        db_session.add(n)
        if with_result:
            db_session.add(models.OpeningResult(
                bid_no=bid_no, basic_price=110_000_000.0, reserved_price=110_500_000.0,
                winner_price=99_000_000.0, winner_rate=89.593,
                winner_company="가나건설", open_date=datetime.now() - timedelta(days=1),
            ))
        db_session.flush()

    def test_result_card_replaces_unconfirmed(self, client, db_session, enforce):
        self._seed(db_session, "PAGE-CLOSED-1")
        html = client.get("/bid/PAGE-CLOSED-1").text

        assert "개찰 결과" in html
        assert "99,000,000원" in html          # 낙찰가
        assert "가나건설" in html               # 낙찰자
        assert "110,000,000원" in html          # 개찰이 알려준 기초금액
        assert "기초금액 미확인" not in html     # 알면서 모른다고 하지 않는다

    def test_reserved_ratio_shown(self, client, db_session, enforce):
        """사정률은 마감 후에만 알 수 있는 값 — 다음 투찰의 감을 잡는 근거."""
        self._seed(db_session, "PAGE-CLOSED-2")
        html = client.get("/bid/PAGE-CLOSED-2").text
        assert "사정률" in html
        assert "100.455%" in html   # 110,500,000 / 110,000,000

    def test_closed_without_result_still_unconfirmed(self, client, db_session, enforce):
        """개찰결과가 아직 없으면 여전히 모른다고 말한다."""
        self._seed(db_session, "PAGE-CLOSED-3", with_result=False)
        html = client.get("/bid/PAGE-CLOSED-3").text
        assert "개찰 결과" not in html
        assert "기초금액 미확인" in html


class TestEnforcementIsInvariant:
    """확정 기초금액 전용은 운영 토글이 아니라 도메인 불변식이다.

    예전엔 BASIS_AMOUNT_ENFORCE 기본값이 False 라 운영 env 한 줄이 빠지면 추정가격
    (presmptPrce)이 기초금액 자리로 되살아나 낙찰하한선이 ~9% 낮게 계산됐다(함정 22).
    계산 안전 규칙은 설정 누락으로 꺼질 수 없어야 한다.
    """

    def test_enforcing_true_even_when_setting_false(self, monkeypatch):
        monkeypatch.setattr(basis.settings, "BASIS_AMOUNT_ENFORCE", False, raising=False)
        assert basis.enforcing() is True

    def test_missing_basis_is_unconfirmed_not_legacy(self, monkeypatch):
        monkeypatch.setattr(basis.settings, "BASIS_AMOUNT_ENFORCE", False, raising=False)
        assert basis.basis_status(_notice(basic=100_000_000.0)) == basis.UNCONFIRMED

    def test_never_falls_back_to_estimated_price(self, monkeypatch):
        monkeypatch.setattr(basis.settings, "BASIS_AMOUNT_ENFORCE", False, raising=False)
        # basic_price 만 있고 확정 기초금액이 없으면 숫자를 주지 않는다 (9% 낮은 '안전' 판정 방지)
        assert basis.confirmed_basis(_notice(basic=100_000_000.0)) is None

    def test_config_default_is_true(self):
        from app.core.config import Settings
        assert Settings.model_fields["BASIS_AMOUNT_ENFORCE"].default is True
