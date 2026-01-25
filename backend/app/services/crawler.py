import requests
import json
from datetime import datetime, timedelta
from typing import List, Optional
from app.db import models
from app.core.config import settings

class CrawlerService:
    # BidPublicInfoService04 / getBidPblancListInfoCnstwk01 (Gongsa - Construction)
    # Updated Endpoint based on user feedback (ad/BidPublicInfoService)
    BASE_URL = "https://apis.data.go.kr/1230000/ad/BidPublicInfoService/getBidPblancListInfoCnstwk"
    
    @staticmethod
    def fetch_notices(page: int = 1, size: int = 50) -> List[dict]:
        """
        Fetch notices from Public Data Portal API (Real Data).
        """
        # Calculate date range (Recent 30 days)
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
        
        try:
            print(f"[Crawler] Fetching from: {CrawlerService.BASE_URL}")
            response = requests.get(CrawlerService.BASE_URL, params=params)
            
            # Check Status
            if response.status_code != 200:
                print(f"[Crawler] Error: {response.status_code}, {response.text}")
                print("[Crawler] Switching to Mock Data (HTTP Error)...")
                return CrawlerService.get_mock_data()
            
            # Parse JSON
            # Note: data.go.kr sometimes returns double stringified JSON or XML error on failure
            try:
                data = response.json()
            except json.JSONDecodeError:
                print(f"[Crawler] JSON Decode Error. Response might be XML or Invalid: {response.text[:200]}")
                return []
                
            response_body = data.get("response", {}).get("body", {})
            if not response_body:
                print(f"[Crawler] No body in response: {data}")
                return []
                
            items = response_body.get("items", [])
            if not items:
                print("[Crawler] No items found.")
                return []
                
            # Handle single item vs list
            if isinstance(items, dict):
                items = [items]
            
            result_list = []
            for item in items:
                # Map API fields to our model
                # bidNtceNo: 공고번호, bidNtceOrd: 차수
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

                notice_dict = {
                    "bid_no": bid_no,
                    "title": title,
                    "content": item.get("bidNtceDtlUrl", ""), # Link as content
                    "basic_price": float(item.get("presmptPrce", 0)),
                    "contract_type": ctype,
                    "start_date": start_dt,
                    "end_date": end_dt
                }
                result_list.append(notice_dict)
                
            print(f"[Crawler] Successfully fetched {len(result_list)} items.")
            return result_list

        except Exception as e:
            print(f"[Crawler] Critical Error: {str(e)}")
            print("[Crawler] Switching to Mock Data for Development...")
            return CrawlerService.get_mock_data()

    @staticmethod
    def get_mock_data() -> List[dict]:
        from datetime import datetime
        return [
            {
                "bid_no": "20240123001",
                "title": "[Mock] 강남구 구민회관 리모델링 공사",
                "content": "http://example.com/notice1",
                "basic_price": 500000000.0,
                "contract_type": "CONSTRUCTION",
                "start_date": datetime.now(),
                "end_date": datetime.now() + timedelta(days=7)
            },
            {
                "bid_no": "20240123002",
                "title": "[Mock] 서초구 도로 포장 공사",
                "content": "http://example.com/notice2",
                "basic_price": 120000000.0,
                "start_date": datetime.now(),
                "end_date": datetime.now() + timedelta(days=5)
            },
            {
                "bid_no": "20240123003",
                "title": "[Mock] 판교 도서관 신축 전기 공사",
                "content": "http://example.com/notice3",
                "basic_price": 350000000.0,
                "start_date": datetime.now(),
                "end_date": datetime.now() + timedelta(days=10)
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
