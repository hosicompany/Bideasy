import requests
import json
from datetime import datetime, timedelta
from typing import List
from app.db import models
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

class CrawlerService:
    # BidPublicInfoService 목록 3종 (공사/용역/물품) — bid_detail.py 와 동일 패턴.
    # 기존엔 공사(Cnstwk) 단일만 호출해 용역·물품이 누락됐고 contract_type 을
    # 제목으로 추론(손실)했음. → 카테고리별 엔드포인트를 fan-out 하고
    # 반환 엔드포인트로 contract_type 을 정확히 태깅.
    _SEARCH_BASE = "https://apis.data.go.kr/1230000/ad/BidPublicInfoService"
    _CATEGORY_ENDPOINTS = {
        "construction": ("/getBidPblancListInfoCnstwk", "CONSTRUCTION"),
        "service": ("/getBidPblancListInfoServc", "SERVICE"),
        "goods": ("/getBidPblancListInfoThng", "GOODS"),
    }
    # 하위호환: 기존 공사 단일 URL 참조 코드용
    BASE_URL = _SEARCH_BASE + "/getBidPblancListInfoCnstwk"

    # Korean region names for smart detection
    REGION_KEYWORDS = [
        "서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종",
        "경기", "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주",
        "고양", "수원", "성남", "용인", "안양", "안산", "화성", "평택",
        "청주", "천안", "전주", "포항", "창원", "김해"
    ]
    
    @staticmethod
    def is_region_keyword(keyword: str) -> bool:
        """Check if keyword is a region name."""
        if not keyword:
            return False
        return any(region in keyword for region in CrawlerService.REGION_KEYWORDS)
    
    @staticmethod
    def parse_bid_method(raw: str) -> str:
        """낙찰자결정방법명 → 전략 키 (첫 토큰).

        API 는 세부 기준까지 붙여서 준다:
          '적격심사제-추정가격 3억원 미만 8천만원 이상인 공사(전기…)'
          '소액수의견적-소액수의견적(2인 이상 견적 제출)-국민연금보험료 등 합산액 감액 적용'
        '-' 앞 첫 토큰만 취해야 BID_STRATEGY 키 · OpeningResult.bid_method 와
        같은 어휘가 된다(그래야 전략 조회·세그먼트 조인이 맞는다).
        """
        if not raw:
            return ""
        return raw.split("-", 1)[0].strip()

    @staticmethod
    def _num(value, cast=float):
        """API 숫자 필드 파싱. 빈 문자열·None·비숫자는 None (0 으로 위장하지 않음)."""
        if value in (None, ""):
            return None
        try:
            return cast(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _map_item(item: dict, contract_type: str) -> dict:
        """OpenAPI item → Notice dict. contract_type 은 호출 엔드포인트에서 확정 전달.

        ⚠️ 필드명은 2026-08-02 에 공사/용역/물품 3종 응답을 실측해 교정했다.
        그 전에는 존재하지 않는 키(`bidMthdNm`·`cntrctMthdNm`·`prtcptLmtRgnNm` 등)를
        읽어 bid_method·region·contract_method 가 **100% 결측**이었고, 그 탓에
        recommend_bid_price 가 전 건 DEFAULT 전략으로 떨어지고 지역 검색이
        무력화돼 있었다. 키를 바꿀 때는 반드시 3종 응답을 다시 실측할 것.
        """
        bid_no = f"{item.get('bidNtceNo')}-{item.get('bidNtceOrd')}"

        # opengDt(개찰일시)를 effective end_date 로 사용 (입찰은 개찰 전 마감)
        opening_str = item.get("opengDt", "")
        try:
            end_dt = datetime.strptime(opening_str, "%Y-%m-%d %H:%M:%S")
        except (ValueError, TypeError):
            end_dt = datetime.now() + timedelta(days=7)

        title = item.get("bidNtceNm", "No Title")
        sucsfbid_mthd = item.get("sucsfbidMthdNm", "") or ""
        # 예산: 공사는 bdgtAmt, 용역·물품은 asignBdgtAmt (엔드포인트별로 다름)
        budget = CrawlerService._num(item.get("bdgtAmt") or item.get("asignBdgtAmt"))

        return {
            "bid_no": bid_no,
            "title": title,
            "content": item.get("bidNtceDtlUrl", ""),
            "basic_price": float(item.get("presmptPrce", 0) or 0),
            "contract_type": contract_type,  # 제목추론 아님 — 엔드포인트로 확정
            "start_date": datetime.now(),
            "end_date": end_dt,
            "organization": item.get("ntceInsttNm", ""),
            "demand_organization": item.get("dmndInsttNm", ""),
            # 전략 선택 키 — 낙찰자결정방법의 첫 토큰
            "bid_method": CrawlerService.parse_bid_method(sucsfbid_mthd),
            "bid_method_detail": sucsfbid_mthd,
            "bid_method_code": item.get("sucsfbidMthdCd", ""),
            "contract_method": item.get("cntrctCnclsMthdNm", ""),
            "bid_submit_method": item.get("bidMethdNm", ""),
            "notice_kind": item.get("ntceKindNm", ""),
            # 공고 명시 낙찰하한율 (용역 등 미제공 건은 None)
            "lower_limit_rate": CrawlerService._num(item.get("sucsfbidLwltRate")),
            "prdprc_total": CrawlerService._num(item.get("totPrdprcNum"), int),
            "prdprc_draw": CrawlerService._num(item.get("drwtPrdprcNum"), int),
            # 공사현장 지역 — 공사 엔드포인트에만 존재. 용역·물품은 결측 유지.
            # (rgnLmtBidLocplcJdgmBssNm 은 '지역제한 판단기준'이라 지역명이 아니다)
            "region": item.get("cnstrtsiteRgnNm", ""),
            "budget_amount": budget,
            "opening_date": item.get("opengDt", ""),
            "international_bid": item.get("intrbidYn", ""),
            "bid_qualification": item.get("bidQlfctRgstDt", ""),
            "rebid_yn": item.get("rbidPermsnYn", ""),
            "re_notice_yn": item.get("reNtceYn", ""),
            "attachment_url": item.get("ntceSpecDocUrl1", ""),
            "attachment_name": item.get("ntceSpecFileNm1", ""),
            # ⚠️ 목록 API 가 제공하지 않는 필드는 아예 넣지 않는다.
            # (bid_type·status·joint_contract·sme_only·big_company_ok·emergency_bid)
            # 예전엔 없는 키를 읽고 기본값 "N" 을 저장해, "중소기업 전용 아님" 같은
            # 확인되지 않은 사실을 단정하고 있었다. 모르는 건 비워 둔다.
        }

    @staticmethod
    def _request_items(url: str, params: dict) -> List[dict]:
        """단일 OpenAPI 호출 → items 리스트(없으면 []). mock fallback 없음."""
        try:
            resp = requests.get(url, params=params, timeout=15)
            if resp.status_code != 200:
                logger.error(f"HTTP {resp.status_code} from {url}: {resp.text[:200]}")
                return []
            try:
                data = resp.json()
            except json.JSONDecodeError:
                logger.error(f"JSON decode error from {url}: {resp.text[:200]}")
                return []
            items = data.get("response", {}).get("body", {}).get("items", [])
            if not items:
                return []
            return [items] if isinstance(items, dict) else items
        except Exception as e:
            logger.error(f"Request error {url}: {e}")
            return []

    @staticmethod
    def fetch_notices(
        page: int = 1,
        size: int = 50,
        keyword: str = None,
        region: str = None,
        category: str = None,
        date_from: str = None,
        date_to: str = None,
    ) -> List[dict]:
        """공고 목록 조회 (공사/용역/물품 fan-out).

        - category: construction|service|goods 지정 시 해당 1종만, None/'all' 이면 3종 fan-out
        - keyword: 제목 검색(bidNtceNm) / region: 기관명 검색(ntceInsttNm)
        - date_from/date_to: 'YYYY-MM-DD' (없으면 최근 5일)
        contract_type 은 호출 엔드포인트로 확정 태깅(제목추론 제거).
        """
        # 조회 카테고리 결정
        if category and category in CrawlerService._CATEGORY_ENDPOINTS:
            cats = [category]
        else:
            cats = list(CrawlerService._CATEGORY_ENDPOINTS.keys())  # 3종 전부

        # 날짜 범위
        end_date_str = (date_to.replace("-", "") if date_to else datetime.now().strftime("%Y%m%d")) + "2359"
        start_date_str = (
            date_from.replace("-", "") if date_from
            else (datetime.now() - timedelta(days=5)).strftime("%Y%m%d")
        ) + "0000"

        merged: List[dict] = []
        for cat in cats:
            path, ctype = CrawlerService._CATEGORY_ENDPOINTS[cat]
            url = CrawlerService._SEARCH_BASE + path
            params = {
                "serviceKey": settings.PUBLIC_DATA_KEY,
                "numOfRows": size,
                "pageNo": page,
                "inqryDiv": 1,  # 1: 목록
                "inqryBgnDt": start_date_str,
                "inqryEndDt": end_date_str,
                "type": "json",
            }
            if region:
                params["ntceInsttNm"] = region
            elif keyword:
                params["bidNtceNm"] = keyword

            items = CrawlerService._request_items(url, params)
            for item in items:
                merged.append(CrawlerService._map_item(item, ctype))
            logger.info(f"[{cat}] {len(items)} items")

        if merged:
            logger.info(f"fetch_notices total {len(merged)} (cats={cats})")
            return merged

        # 실데이터 없음.
        # 운영(production)에서는 mock 절대 반환 안 함 (가짜 [Mock] 공고가 DB 오염).
        # 개발에서만, 필터 없는 기본 조회에 한해 mock 제공.
        if (
            settings.APP_ENV != "production"
            and not keyword and not region and not category
        ):
            logger.warning("No real notices — returning mock data (dev only)")
            return CrawlerService.get_mock_data()
        return []

    @staticmethod
    def get_mock_data() -> List[dict]:
        from datetime import datetime
        now = datetime.now()
        
        # Helper to offset days
        def days(n): return now + timedelta(days=n)
        
        return [
            {
                "bid_no": "20240123001",
                "title": "[Mock] 부산광역시 기장군 청사 리모델링 공사",
                "content": "http://example.com/notice1",
                "basic_price": 500000000.0,
                "contract_type": "CONSTRUCTION",
                "start_date": now,
                "end_date": days(7),
                "organization": "부산광역시 기장군",
                "demand_organization": "기장군청",
                "bid_method": "전자입찰",
                "contract_method": "일반경쟁입찰",
                "bid_type": "공사",
                "status": "일반공고",
                "region": "부산광역시",
                "budget_amount": 550000000.0,
                "opening_date": days(8).strftime("%Y-%m-%d %H:%M"),
                "international_bid": "N",
                "joint_contract": "Y",
                "sme_only": "Y",
                "big_company_ok": "N",
                "bid_qualification": "부산광역시 소재 전기공사업 등록업체",
                "emergency_bid": "N",
                "rebid_yn": "N",
                "attachment_url": "https://www.g2b.go.kr/example_spec.hwp", 
                "attachment_name": "공고규격서.hwp",
                "a_value": 15000000, # Mock A Value (약 3%)
                "net_cost": 440000000 # Mock Net Cost
            },
            {
                "bid_no": "20240123002",
                "title": "[Mock] 서초구 보건소 전기 소방 공사",
                "content": "http://example.com/notice2",
                "basic_price": 120000000.0,
                "contract_type": "CONSTRUCTION",
                "start_date": now,
                "end_date": days(5),
                "organization": "서울특별시 서초구",
                "demand_organization": "서초구보건소",
                "bid_method": "전자입찰",
                "contract_method": "제한경쟁",
                "region": "서울특별시",
                "budget_amount": 130000000.0,
                "opening_date": days(6).strftime("%Y-%m-%d %H:%M"),
                "sme_only": "N",
                "attachment_url": "",
                "attachment_name": ""
            },
            {
                "bid_no": "20240123003",
                "title": "[Mock] 경기도 고양시 도로포장 유지보수",
                "content": "http://example.com/notice3",
                "basic_price": 350000000.0,
                "contract_type": "CONSTRUCTION",
                "organization": "경기도 고양시",
                "region": "경기도",
                "opening_date": days(10).strftime("%Y-%m-%d %H:%M"),
                "end_date": days(9),
                "start_date": now
            },
            {
                "bid_no": "20240123004",
                "title": "[Mock] 인천국제공항 보안검색 장비 유지관리 용역",
                "content": "http://example.com/notice4",
                "basic_price": 2100000000.0,
                "contract_type": "SERVICE",
                "organization": "인천국제공항공사",
                "region": "인천광역시",
                "opening_date": days(14).strftime("%Y-%m-%d %H:%M"),
                "end_date": days(13),
                "start_date": now,
                "big_company_ok": "Y"
            },
            {
                "bid_no": "20240123005",
                "title": "[Mock] 세종시 스마트시티 관제센터 시스템 구축",
                "content": "http://example.com/notice5",
                "basic_price": 4500000000.0,
                "contract_type": "GOODS",
                "organization": "세종특별자치시",
                "region": "세종특별자치시",
                "opening_date": days(20).strftime("%Y-%m-%d %H:%M"),
                "end_date": days(19),
                "start_date": now
            },
            {
                "bid_no": "20240123006",
                "title": "[Mock] 강원도 평창군 마을회관 신축공사 (긴급)",
                "content": "http://example.com/notice6",
                "basic_price": 80000000.0,
                "contract_type": "CONSTRUCTION",
                "organization": "강원도 평창군",
                "region": "강원도",
                "opening_date": days(3).strftime("%Y-%m-%d %H:%M"),
                "end_date": days(2),
                "start_date": now,
                "emergency_bid": "Y"
            },
            {
                "bid_no": "20240123007",
                "title": "[Mock] 전라남도 여수시 해안도로 가로등 교체",
                "content": "http://example.com/notice7",
                "basic_price": 150000000.0,
                "contract_type": "CONSTRUCTION",
                "organization": "전라남도 여수시",
                "region": "전라남도",
                "opening_date": days(5).strftime("%Y-%m-%d %H:%M"),
                "end_date": days(4),
                "start_date": now
            },
            {
                "bid_no": "20240123008",
                "title": "[Mock] 대전광역시 교육청 학교 급식기구 구매",
                "content": "http://example.com/notice8",
                "basic_price": 60000000.0,
                "contract_type": "GOODS",
                "organization": "대전광역시 교육청",
                "region": "대전광역시",
                "opening_date": days(7).strftime("%Y-%m-%d %H:%M"),
                "end_date": days(6),
                "start_date": now
            }
        ]

    # 기존 행 갱신에서 제외할 컬럼 — 최초 수집 시각은 재크롤로 바뀌면 안 된다.
    _UPSERT_SKIP = frozenset({"bid_no", "start_date"})

    @staticmethod
    def save_notices(db_session, notices_data: List[dict]):
        """공고를 DB 에 upsert. 반환은 **신규 삽입 건수**(기존 동작 호환).

        예전엔 신규만 insert 하고 기존 행은 건드리지 않았다. 그 탓에 매핑이
        고쳐져도 이미 저장된 공고는 빈 필드로 영원히 남았다(2026-08-02 실측:
        공사 3,511건 전부 bid_method 결측). 공고는 정정(chgNtceRsn)도 되므로
        재크롤 시 최신 값을 반영하는 게 맞다.

        A값(`a_value`)·`net_cost` 는 별도 파이프라인(익스텐션 크라우드소스·
        첨부파싱)이 채우는 값이라 `_map_item` 결과에 없고, 따라서 여기서
        덮어써지지 않는다 — 이 불변식을 깨지 말 것.
        """
        saved_count = 0
        for data in notices_data:
            existing = db_session.query(models.Notice).filter(models.Notice.bid_no == data["bid_no"]).first()
            if not existing:
                notice = models.Notice(**data)
                db_session.add(notice)
                saved_count += 1
                continue
            # 기존 행 갱신 — None 은 "API 가 값을 주지 않음"이라 기존 값을 지우지 않는다.
            for key, value in data.items():
                if key in CrawlerService._UPSERT_SKIP or value is None:
                    continue
                setattr(existing, key, value)
        db_session.commit()
        return saved_count
