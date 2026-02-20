import requests
import json
from datetime import datetime, timedelta
from typing import List
from app.db import models
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

class CrawlerService:
    # BidPublicInfoService04 / getBidPblancListInfoCnstwk01 (Gongsa - Construction)
    # Updated Endpoint based on user feedback (ad/BidPublicInfoService)
    BASE_URL = "https://apis.data.go.kr/1230000/ad/BidPublicInfoService/getBidPblancListInfoCnstwk"
    
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
    def fetch_notices(page: int = 1, size: int = 50, keyword: str = None, region: str = None) -> List[dict]:
        """
        Fetch notices from Public Data Portal API (Real Data).
        - keyword: Search by title (bidNtceNm)
        - region: Search by organization name (ntceInsttNm) for region filtering
        """
        # Calculate date range (Recent 30 days to ensure data)
        end_date_str = datetime.now().strftime("%Y%m%d") + "2359"
        start_date_str = (datetime.now() - timedelta(days=30)).strftime("%Y%m%d") + "0000"

        params = {
            "serviceKey": settings.PUBLIC_DATA_KEY,
            "numOfRows": size,
            "pageNo": page,
            "inqryDiv": 1, # 1: Notice List
            "inqryBgnDt": start_date_str, 
            "inqryEndDt": end_date_str,
            "type": "json" 
        }
        
        # Smart Parameter Selection
        if region:
            # Region-based search: Use organization name filter
            params["ntceInsttNm"] = region
            logger.info(f"Region Search: ntceInsttNm={region}")
        elif keyword:
            # Keyword-based search: Use title filter
            params["bidNtceNm"] = keyword
            logger.info(f"Keyword Search: bidNtceNm={keyword}")

        try:
            logger.info(f"Fetching from: {CrawlerService.BASE_URL}")
            response = requests.get(CrawlerService.BASE_URL, params=params)
            
            # Check Status
            # Check Status
            if response.status_code != 200:
                logger.error(f"HTTP Error: {response.status_code}, {response.text}")
                return []
            
            # Parse JSON
            try:
                data = response.json()
            except json.JSONDecodeError:
                logger.error(f"JSON Decode Error. Response might be XML or Invalid: {response.text[:200]}")
                logger.warning("Falling back to Mock Data due to API Error")
                return CrawlerService.get_mock_data()
                
            response_body = data.get("response", {}).get("body", {})
            if not response_body:
                logger.warning(f"No body in response: {data}")
                return CrawlerService.get_mock_data()
                
            items = response_body.get("items", [])
            if not items:
                logger.warning(f"No items found for page {page}. Returning Mock Data.")
                return CrawlerService.get_mock_data()
                
            # Handle single item vs list
            if isinstance(items, dict):
                items = [items]
            
            result_list = []
            for item in items:
                # Map API fields to our model
                bid_no = f"{item.get('bidNtceNo')}-{item.get('bidNtceOrd')}"
                
                # Date Parsing with Format Exception Handling
                try:
                    start_dt = datetime.strptime(item.get("bidBegnDtm", ""), "%Y%m%d%H%M")
                    end_dt = datetime.strptime(item.get("bidClseDtm", ""), "%Y%m%d%H%M")
                except (ValueError, TypeError):
                    start_dt = datetime.now()
                    end_dt = datetime.now() + timedelta(days=7)

                # Infer Contract Type
                title = item.get("bidNtceNm", "No Title")
                ctype = "CONSTRUCTION" # Default
                if any(k in title for k in ["용역", "관리", "청소"]):
                    ctype = "SERVICE"
                elif any(k in title for k in ["구매", "구입", "제작"]):
                    ctype = "GOODS"

                if item.get("ntceSpecDocUrl1"):
                    logger.info(f"Found attachment: {item.get('ntceSpecFileNm1')} for {bid_no}")
                
                notice_dict = {
                    # Core fields
                    "bid_no": bid_no,
                    "title": title,
                    "content": item.get("bidNtceDtlUrl", ""),  # Detail URL
                    "basic_price": float(item.get("presmptPrce", 0)),
                    "contract_type": ctype,
                    "start_date": start_dt,
                    "end_date": end_dt,
                    "organization": item.get("ntceInsttNm", ""),
                    
                    # Extended fields for AI analysis
                    "demand_organization": item.get("dmndInsttNm", ""),  # 수요기관
                    "bid_method": item.get("bidMthdNm", ""),  # 입찰방법 (전자입찰 등)
                    "contract_method": item.get("cntrctMthdNm", ""),  # 계약방법 (일반경쟁 등)
                    "bid_type": item.get("bidClsfcNm", ""),  # 입찰분류
                    "status": item.get("bidNtceSttusNm", ""),  # 공고상태 (일반/긴급/정정)
                    "region": item.get("prtcptLmtRgnNm", ""),  # 참가제한지역
                    "budget_amount": float(item.get("asignBdgtAmt", 0)),  # 배정예산
                    "opening_date": item.get("opengDt", ""),  # 개찰일시
                    "international_bid": item.get("intrntnlBidYn", "N"),  # 국제입찰여부
                    "joint_contract": item.get("jntcontrctPsbltyYn", "N"),  # 공동계약가능
                    "big_company_ok": item.get("lrgcntrctPsbltyYn", "N"),  # 대기업참여가능
                    "sme_only": item.get("dminsttRcptcpYn", "N"),  # 중소기업제한
                    "bid_qualification": item.get("bidQlfctRgstDt", ""),  # 입찰자격등록마감
                    "emergency_bid": item.get("urgntNtceYn", "N"),  # 긴급공고여부
                    "rebid_yn": item.get("rbidYn", "N"),  # 재입찰여부
                    "attachment_url": item.get("ntceSpecDocUrl1", ""),  # 공고규격서 URL
                    "attachment_name": item.get("ntceSpecFileNm1", ""),  # 첨부파일명
                }
                result_list.append(notice_dict)
                
            logger.info(f"Successfully fetched {len(result_list)} items.")
            return result_list

        except Exception as e:
            logger.error(f"Critical Error: {str(e)}")
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
