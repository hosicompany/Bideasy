import requests
from datetime import datetime
from typing import List, Optional
from app.db import models
from app.core.config import settings

class CrawlerService:
    BASE_URL = "https://apis.data.go.kr/1230000/BidPublicInfoService04" # URL Example
    
    @staticmethod
    def fetch_notices(page: int = 1, size: int = 10) -> List[dict]:
        """
        Fetch notices from Public Data Portal API.
        Current implementation is a mock since we don't have a real API Key yet.
        """
        # Todo: Implement real API call using requests
        # params = {
        #     "serviceKey": settings.PUBLIC_DATA_KEY,
        #     "numOfRows": size,
        #     "pageNo": page,
        #     "inqryDiv": 1, 
        #     ...
        # }
        
        # Mock Data for Development
        mock_data = [
            {
                "bid_no": "20240121001",
                "title": "[Hosi Company] 강남구 구민회관 리모델링 공사",
                "content": "<p>상세 공고 내용입니다...</p>",
                "basic_price": 500000000.0,
                "start_date": datetime.now(),
                "end_date": datetime.now()
            },
            {
                "bid_no": "20240121002",
                "title": "서초구 도로 포장 공사",
                "content": "<p>도로 포장 공사 상세...</p>",
                "basic_price": 120000000.0,
                "start_date": datetime.now(),
                "end_date": datetime.now()
            }
        ]
        return mock_data

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
