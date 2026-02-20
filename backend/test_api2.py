import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
import os

load_dotenv()
api_key = os.getenv('PUBLIC_DATA_KEY')

from app.services.g2b_api_service import G2BApiService

async def test():
    service = G2BApiService(api_key)
    
    try:
        # 물품 낙찰현황 테스트
        print("=== 물품 낙찰현황 테스트 ===")
        result = await service.get_bid_status(
            bid_type="goods",
            start_date="20240101",
            end_date="20240131",
            num_of_rows=3,
            page_no=1
        )
        
        body = result.get("body", {})
        print(f"결과코드: {result.get('header', {}).get('resultCode')}")
        print(f"총 건수: {body.get('totalCount')}")
        
        items = body.get("items", [])
        if items:
            print(f"조회 건수: {len(items)}개")
            if isinstance(items, list) and len(items) > 0:
                print(f"첫번째 항목: {items[0].get('bidNtceNm', 'N/A')[:50]}...")
        
        print("\n=== 공사 낙찰현황 테스트 ===")
        result2 = await service.get_bid_status(
            bid_type="construction",
            start_date="20240101",
            end_date="20240131",
            num_of_rows=3,
            page_no=1
        )
        
        body2 = result2.get("body", {})
        print(f"결과코드: {result2.get('header', {}).get('resultCode')}")
        print(f"총 건수: {body2.get('totalCount')}")
        
    finally:
        await service.close()

asyncio.run(test())
