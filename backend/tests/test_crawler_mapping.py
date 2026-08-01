"""공고 API 필드 매핑 회귀 테스트 (2026-08-02).

배경: `_map_item` 이 응답에 존재하지 않는 키(`bidMthdNm`·`cntrctMthdNm`·
`prtcptLmtRgnNm` 등)를 읽어 공사 공고 3,511건의 bid_method·region 이 100%
결측이었다. 그 탓에 `recommend_bid_price` 가 전 건 DEFAULT 전략으로 떨어졌다.

아래 샘플은 2026-08-02 실제 API 응답에서 필드명을 그대로 따온 것이다.
키 이름을 바꾸려면 3종(공사/용역/물품) 응답을 다시 실측할 것.
"""
from app.db import models
from app.services.crawler import CrawlerService


# --- 실제 응답에서 발췌한 최소 샘플 ---------------------------------
CONSTRUCTION_ITEM = {
    "bidNtceNo": "R26BK01557528", "bidNtceOrd": "000",
    "bidNtceNm": "○○ 전기공사", "opengDt": "2026-08-05 11:00:00",
    "bidMethdNm": "전자입찰",
    "cntrctCnclsMthdNm": "수의계약",
    "sucsfbidMthdNm": "소액수의견적-소액수의견적(2인 이상 견적 제출)-국민연금보험료 등 합산액 감액 적용",
    "sucsfbidMthdCd": "낙030001",
    "sucsfbidLwltRate": "89.745",
    "totPrdprcNum": "15", "drwtPrdprcNum": "4",
    "presmptPrce": "24901819", "bdgtAmt": "39400000",
    "cnstrtsiteRgnNm": "충청남도 부여군",
    "ntceInsttNm": "부여군", "dmndInsttNm": "부여군",
    "ntceKindNm": "등록공고", "rbidPermsnYn": "Y",
    "intrbidYn": "N", "reNtceYn": "N",
}

SERVICE_ITEM = {
    "bidNtceNo": "R26BK09990001", "bidNtceOrd": "000",
    "bidNtceNm": "○○ 용역", "opengDt": "2026-08-06 10:00:00",
    "bidMethdNm": "전자입찰",
    "cntrctCnclsMthdNm": "제한경쟁",
    "sucsfbidMthdNm": "협상에의한계약-협상에 의한 낙찰자 결정",
    "sucsfbidLwltRate": "",          # 용역은 미제공
    "totPrdprcNum": "", "drwtPrdprcNum": "",
    "presmptPrce": "27272727",
    "asignBdgtAmt": "30000000",      # 용역·물품은 이 키
    "ntceInsttNm": "○○청", "ntceKindNm": "등록공고",
}

GOODS_ITEM = {
    "bidNtceNo": "R26BK08880001", "bidNtceOrd": "000",
    "bidNtceNm": "○○ 물품 구매", "opengDt": "2026-08-07 14:00:00",
    "cntrctCnclsMthdNm": "제한경쟁",
    "sucsfbidMthdNm": "적격심사제-추정가격이 고시금액 미만인 물품 제조 또는 구매입찰",
    "sucsfbidLwltRate": "86.245",
    "totPrdprcNum": "15", "drwtPrdprcNum": "4",
    "presmptPrce": "181818182", "asignBdgtAmt": "200000000",
    "ntceInsttNm": "○○공사", "ntceKindNm": "등록공고",
}


class TestParseBidMethod:
    """낙찰자결정방법 → 전략 키(첫 토큰) 추출."""

    def test_extracts_first_token(self):
        assert CrawlerService.parse_bid_method(
            "적격심사제-추정가격 3억원 미만 8천만원 이상인 공사(전기ㆍ정보통신)"
        ) == "적격심사제"

    def test_handles_multiple_hyphens(self):
        # '-' 가 3개 있어도 첫 토큰만
        assert CrawlerService.parse_bid_method(
            "소액수의견적-소액수의견적(2인 이상 견적 제출)-국민연금보험료 등 합산액 감액 적용"
        ) == "소액수의견적"

    def test_no_hyphen_returns_whole(self):
        assert CrawlerService.parse_bid_method("최저가낙찰제") == "최저가낙찰제"

    def test_empty_is_safe(self):
        assert CrawlerService.parse_bid_method("") == ""
        assert CrawlerService.parse_bid_method(None) == ""

    def test_matches_strategy_keys(self):
        """추출 결과가 BID_STRATEGY 키와 같은 어휘여야 전략 조회가 맞는다."""
        from app.services.calculator import BID_STRATEGY
        parsed = CrawlerService.parse_bid_method(
            CONSTRUCTION_ITEM["sucsfbidMthdNm"]
        )
        assert parsed in BID_STRATEGY


class TestMapItemConstruction:
    def test_core_fields(self):
        m = CrawlerService._map_item(CONSTRUCTION_ITEM, "CONSTRUCTION")
        assert m["bid_no"] == "R26BK01557528-000"
        assert m["bid_method"] == "소액수의견적"       # ← 예전엔 "" 였다
        assert m["contract_method"] == "수의계약"      # ← 예전엔 "" 였다
        assert m["region"] == "충청남도 부여군"         # ← 예전엔 "" 였다
        assert m["bid_submit_method"] == "전자입찰"
        assert m["basic_price"] == 24901819.0

    def test_lower_limit_and_prdprc(self):
        m = CrawlerService._map_item(CONSTRUCTION_ITEM, "CONSTRUCTION")
        assert m["lower_limit_rate"] == 89.745
        assert m["prdprc_total"] == 15
        assert m["prdprc_draw"] == 4

    def test_budget_uses_bdgtAmt(self):
        m = CrawlerService._map_item(CONSTRUCTION_ITEM, "CONSTRUCTION")
        assert m["budget_amount"] == 39400000.0

    def test_detail_preserved_for_a_value_rule(self):
        """A값 감액 적용 여부는 원문에만 있으므로 반드시 보존돼야 한다."""
        m = CrawlerService._map_item(CONSTRUCTION_ITEM, "CONSTRUCTION")
        assert "국민연금보험료" in m["bid_method_detail"]
        assert m["bid_method_code"] == "낙030001"

    def test_unavailable_fields_are_not_fabricated(self):
        """목록 API 가 안 주는 필드에 'N' 같은 기본값을 넣지 않는다."""
        m = CrawlerService._map_item(CONSTRUCTION_ITEM, "CONSTRUCTION")
        for absent in ("bid_type", "status", "joint_contract",
                       "sme_only", "big_company_ok", "emergency_bid"):
            assert absent not in m


class TestMapItemServiceGoods:
    def test_service_budget_uses_asign_key(self):
        m = CrawlerService._map_item(SERVICE_ITEM, "SERVICE")
        assert m["budget_amount"] == 30000000.0

    def test_service_missing_rate_is_none_not_zero(self):
        """용역은 하한율 미제공 — 0 으로 위장하면 '하한율 0%'로 오독된다."""
        m = CrawlerService._map_item(SERVICE_ITEM, "SERVICE")
        assert m["lower_limit_rate"] is None
        assert m["prdprc_total"] is None

    def test_service_bid_method(self):
        m = CrawlerService._map_item(SERVICE_ITEM, "SERVICE")
        assert m["bid_method"] == "협상에의한계약"

    def test_goods_fields(self):
        m = CrawlerService._map_item(GOODS_ITEM, "GOODS")
        assert m["bid_method"] == "적격심사제"
        assert m["lower_limit_rate"] == 86.245
        assert m["budget_amount"] == 200000000.0
        assert m["region"] == ""      # 물품은 현장지역 개념 없음


def _item(base: dict, notice_no: str) -> dict:
    """샘플을 복제하고 공고번호만 교체.

    save_notices 는 commit 하므로 db_session fixture 의 rollback 으로 지워지지
    않는다 → 커밋하는 테스트는 서로 다른 bid_no 를 써야 격리된다.
    """
    return {**base, "bidNtceNo": notice_no}


class TestSaveNoticesUpsert:
    def test_inserts_new(self, db_session):
        data = [CrawlerService._map_item(_item(CONSTRUCTION_ITEM, "UPSERT-INS"), "CONSTRUCTION")]
        assert CrawlerService.save_notices(db_session, data) == 1
        row = db_session.query(models.Notice).filter_by(bid_no="UPSERT-INS-000").first()
        assert row.bid_method == "소액수의견적"

    def test_updates_existing_row(self, db_session):
        """예전엔 신규만 insert 해서, 매핑을 고쳐도 기존 행이 빈 채로 남았다."""
        db_session.add(models.Notice(
            bid_no="UPSERT-UPD-000", title="옛 제목",
            basic_price=1.0, contract_type="CONSTRUCTION",
            bid_method="", region="",
        ))
        db_session.commit()

        data = [CrawlerService._map_item(_item(CONSTRUCTION_ITEM, "UPSERT-UPD"), "CONSTRUCTION")]
        inserted = CrawlerService.save_notices(db_session, data)

        assert inserted == 0                      # 신규 아님
        row = db_session.query(models.Notice).filter_by(bid_no="UPSERT-UPD-000").first()
        assert row.bid_method == "소액수의견적"     # 갱신됨
        assert row.region == "충청남도 부여군"
        assert row.lower_limit_rate == 89.745
        assert row.title == "○○ 전기공사"

    def test_upsert_preserves_a_value(self, db_session):
        """A값은 별도 파이프라인 소유 — 재크롤이 덮어쓰면 안 된다."""
        db_session.add(models.Notice(
            bid_no="UPSERT-AVAL-000", title="기존", basic_price=1.0,
            contract_type="CONSTRUCTION", a_value=15_000_000, net_cost=900,
        ))
        db_session.commit()

        CrawlerService.save_notices(
            db_session,
            [CrawlerService._map_item(_item(CONSTRUCTION_ITEM, "UPSERT-AVAL"), "CONSTRUCTION")],
        )
        row = db_session.query(models.Notice).filter_by(bid_no="UPSERT-AVAL-000").first()
        assert row.a_value == 15_000_000
        assert row.net_cost == 900

    def test_upsert_preserves_start_date(self, db_session):
        """최초 수집 시각은 재크롤로 바뀌면 안 된다."""
        from datetime import datetime
        first_seen = datetime(2026, 1, 1, 9, 0, 0)
        db_session.add(models.Notice(
            bid_no="UPSERT-SD-000", title="기존", basic_price=1.0,
            contract_type="CONSTRUCTION", start_date=first_seen,
        ))
        db_session.commit()

        CrawlerService.save_notices(
            db_session,
            [CrawlerService._map_item(_item(CONSTRUCTION_ITEM, "UPSERT-SD"), "CONSTRUCTION")],
        )
        row = db_session.query(models.Notice).filter_by(bid_no="UPSERT-SD-000").first()
        assert row.start_date == first_seen

    def test_none_does_not_erase_existing(self, db_session):
        """API 가 값을 안 준 필드(None)로 기존 값을 지우지 않는다."""
        db_session.add(models.Notice(
            bid_no="UPSERT-NONE-000", title="기존 용역", basic_price=1.0,
            contract_type="SERVICE", lower_limit_rate=87.745,
        ))
        db_session.commit()

        # SERVICE_ITEM 은 sucsfbidLwltRate 가 빈 문자열 → None
        CrawlerService.save_notices(
            db_session, [CrawlerService._map_item(_item(SERVICE_ITEM, "UPSERT-NONE"), "SERVICE")]
        )
        row = db_session.query(models.Notice).filter_by(bid_no="UPSERT-NONE-000").first()
        assert row.lower_limit_rate == 87.745


class TestBidDetailMapping:
    """단건조회(_format_bid_detail)도 같은 오타를 갖고 있었다."""

    def test_format_uses_real_keys(self):
        from app.services.bid_detail import BidDetailService
        d = BidDetailService._format_bid_detail(CONSTRUCTION_ITEM)
        assert d["contract_method"] == "수의계약"
        assert d["bid_method"].startswith("소액수의견적")
        assert d["region"] == "충청남도 부여군"
        assert d["budget_amount"] == "39400000"

    def test_analysis_context_handles_string_prices(self):
        """API 는 금액을 문자열로 준다 — 숫자 포맷에서 TypeError 가 나면 안 된다."""
        from app.services.bid_detail import BidDetailService
        d = BidDetailService._format_bid_detail(CONSTRUCTION_ITEM)
        ctx = BidDetailService.get_analysis_context(d)
        assert "24,901,819원" in ctx
        assert "39,400,000원" in ctx
        assert "낙찰하한율: 89.745" in ctx
