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
    def _map_item(item: dict, contract_type: str) -> dict:
        """OpenAPI item → Notice dict. contract_type 은 호출 엔드포인트에서 확정 전달."""
        bid_no = f"{item.get('bidNtceNo')}-{item.get('bidNtceOrd')}"

        # opengDt(개찰일시)를 effective end_date 로 사용 (입찰은 개찰 전 마감)
        opening_str = item.get("opengDt", "")
        try:
            end_dt = datetime.strptime(opening_str, "%Y-%m-%d %H:%M:%S")
        except (ValueError, TypeError):
            end_dt = datetime.now() + timedelta(days=7)

        title = item.get("bidNtceNm", "No Title")
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
            "bid_method": item.get("bidMthdNm", ""),
            "contract_method": item.get("cntrctMthdNm", ""),
            "bid_type": item.get("bidClsfcNm", ""),
            "status": item.get("bidNtceSttusNm", ""),
            "region": item.get("prtcptLmtRgnNm", ""),
            "budget_amount": float(item.get("asignBdgtAmt", 0) or 0),
            "opening_date": item.get("opengDt", ""),
            "international_bid": item.get("intrntnlBidYn", "N"),
            "joint_contract": item.get("jntcontrctPsbltyYn", "N"),
            "big_company_ok": item.get("lrgcntrctPsbltyYn", "N"),
            "sme_only": item.get("dminsttRcptcpYn", "N"),
            "bid_qualification": item.get("bidQlfctRgstDt", ""),
            "emergency_bid": item.get("urgntNtceYn", "N"),
            "rebid_yn": item.get("rbidYn", "N"),
            "attachment_url": item.get("ntceSpecDocUrl1", ""),
            "attachment_name": item.get("ntceSpecFileNm1", ""),
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

        # 실데이터 없음 → mock 은 필터 없는 기본 조회에서만 (검색결과 오염 방지)
        if not keyword and not region and not category:
            logger.warning("No real notices — returning mock data (default fetch only)")
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

    @staticmethod
    def save_notices(db_session, notices_data: List[dict]):
        """
        Save fetched notices to database.
        """
        saved_count = 0
        for data in notices_data:
            existing = db_session.query(models.Notice).filter(models.Notice.bid_no == data["bid_no"]).first()
            if not existing:
                notice = models.Notice(**data)
                db_session.add(notice)
                saved_count += 1
        db_session.commit()
        return saved_count
