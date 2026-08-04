"""공사 기초금액 수집 테스트.

지키려는 것:
1. `basic_price`(추정가격)를 절대 건드리지 않는다 — 두 기준이 다시 섞이면 사고다
2. 기초금액이 없는 응답은 저장하지 않는다 (추정 금지)
3. A값은 구성요소 합계이고 출처가 tier0 로 남는다
4. 공고가 없으면 유령 행을 만들지 않는다
"""
from datetime import datetime

from app.db import models
from app.services import basis_amount_crawler as bac


def _item(**over):
    """실제 API 응답 형태 (2026-08-03 운영 실측)."""
    item = {
        "bidNtceNo": "R26BK01661038",
        "bidNtceOrd": "000",
        "bssamt": "148885000",
        "bssamtOpenDt": "2026-08-01 10:09:06",
        "bidPrceCalclAYn": "Y",
        "rsrvtnPrceRngBgnRate": "-2",
        "rsrvtnPrceRngEndRate": "+2",
        "npnInsrprm": "1221931",
        "mrfnHealthInsrprm": "924810",
        "odsnLngtrmrcprInsrprm": "121519",
        "rtrfundNon": "591672",
        "sftyMngcst": "2592638",
        "qltyMngcst": "0",
        "envCnsrvcst": "0",
        "sftyChckMngcst": "0",
        "scontrctPayprcePayGrntyFee": "0",
    }
    item.update(over)
    return item


def _notice(bid_no="R26BK01661038-000", basic=135_350_000.0):
    return models.Notice(
        bid_no=bid_no, title="지하수개발공사", content="",
        basic_price=basic, contract_type="CONSTRUCTION",
        start_date=datetime(2026, 8, 1), end_date=datetime(2026, 8, 10),
        organization="A기관",
    )


class TestParseItem:
    def test_reads_bssamt(self):
        kw = bac.parse_item(_item())
        assert kw["basis_amount"] == 148_885_000.0
        assert kw["bid_no"] == "R26BK01661038-000"

    def test_a_value_is_sum_of_components(self):
        kw = bac.parse_item(_item())
        assert kw["a_value"] == 1_221_931 + 924_810 + 121_519 + 591_672 + 2_592_638

    def test_prdprc_range_is_not_assumed_three_percent(self):
        """±3% 고정이 아니다 — 실측 ±2% 공고가 존재한다."""
        kw = bac.parse_item(_item())
        assert kw["prdprc_range_bgn"] == -2.0
        assert kw["prdprc_range_end"] == 2.0

    def test_missing_bssamt_is_dropped(self):
        """기초금액이 없으면 저장하지 않는다 — 추정 금지."""
        assert bac.parse_item(_item(bssamt="")) is None
        assert bac.parse_item(_item(bssamt="0")) is None

    def test_applicable_flag_is_kept(self):
        """N 이면 A값 0 이 정상 — 결측과 구분돼야 한다."""
        assert bac.parse_item(_item(bidPrceCalclAYn="N"))["a_value_applicable"] == "N"


class TestApplyToNotice:
    def test_does_not_touch_basic_price(self, db_session):
        """⛔ 이 테스트가 이번 사고의 재발 방지선이다."""
        n = _notice(basic=135_350_000.0)
        db_session.add(n)
        db_session.flush()

        bac.apply_to_notice(db_session, bac.parse_item(_item()))
        db_session.flush()

        assert n.basic_price == 135_350_000.0, "basic_price 를 덮었다 — 기준이 다시 섞인다"
        assert n.basis_amount == 148_885_000.0

    def test_sets_a_value_with_tier0_source(self, db_session):
        n = _notice()
        db_session.add(n)
        db_session.flush()

        bac.apply_to_notice(db_session, bac.parse_item(_item()))
        db_session.flush()

        assert n.a_value == 5_452_570
        assert n.a_value_source == "tier0"

    def test_tier0_overrides_other_tiers(self, db_session):
        """조달청이 공고에 실어 준 값이 크라우드소스·첨부파싱보다 정확하다."""
        n = _notice()
        n.a_value = 999
        n.a_value_source = "tier2"
        db_session.add(n)
        db_session.flush()

        bac.apply_to_notice(db_session, bac.parse_item(_item()))
        db_session.flush()

        assert n.a_value == 5_452_570
        assert n.a_value_source == "tier0"

    def test_no_notice_creates_nothing(self, db_session):
        """공고가 아직 없으면 유령 행을 만들지 않는다."""
        before = db_session.query(models.Notice).count()
        got = bac.apply_to_notice(db_session, bac.parse_item(_item(bidNtceNo="R26BK09999999")))
        assert got == "no_notice"
        assert db_session.query(models.Notice).count() == before

    def test_idempotent(self, db_session):
        n = _notice()
        db_session.add(n)
        db_session.flush()
        kw = bac.parse_item(_item())

        assert bac.apply_to_notice(db_session, kw) == "updated"
        db_session.flush()
        assert bac.apply_to_notice(db_session, kw) == "unchanged"

    def test_basis_amount_at_is_parsed(self, db_session):
        n = _notice()
        db_session.add(n)
        db_session.flush()
        bac.apply_to_notice(db_session, bac.parse_item(_item()))
        db_session.flush()
        assert n.basis_amount_at == datetime(2026, 8, 1, 10, 9, 6)


class TestSanity:
    def test_bssamt_is_about_1_1x_presmpt(self):
        """추정가격 × 1.1 ≈ 기초금액 — 하지만 코드가 이 관계를 쓰면 안 된다.

        실측 218건 중 2건은 두 값이 같았다. 여기서는 테스트 데이터가 현실적인지
        확인만 하고, 프로덕션 코드는 언제나 API 실값을 쓴다.
        """
        kw = bac.parse_item(_item())
        assert 1.05 < kw["basis_amount"] / 135_350_000.0 < 1.15
