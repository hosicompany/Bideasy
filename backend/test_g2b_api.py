"""
조달청 API 연동 테스트
"""
import asyncio
import os
from dotenv import load_dotenv

load_dotenv()

import sys
sys.path.insert(0, '.')
from app.services.g2b_api_service import G2BApiService

async def test_api():
    api_key = os.getenv("PUBLIC_DATA_KEY")
    print(f"API Key: {api_key[:20]}...{api_key[-10:]}")
    
    service = G2BApiService(api_key)
    
    try:
        # 1. 물품 낙찰정보 조회 (최근 7일)
        print("\n" + "="*50)
        print("1. 물품 낙찰정보 조회")
        print("="*50)
        
        result = await service.get_bid_results(
            bid_type="goods",
            num_of_rows=5
        )
        
        print(f"Response Header: {result.get('header', {})}")
        
        body = result.get("body", {})
        total_count = body.get("totalCount", 0)
        print(f"Total Count: {total_count}")
        
        items = body.get("items", {})
        if isinstance(items, dict):
            items = items.get("item", [])
        
        if items:
            print(f"\nSample Data ({min(3, len(items))} items):")
            for i, item in enumerate(items[:3]):
                print(f"\n[{i+1}] {item.get('bidNtceNm', 'N/A')[:50]}")
                print(f"    - 공고번호: {item.get('bidNtceNo', 'N/A')}")
                print(f"    - 낙찰금액: {item.get('sucsfbidAmt', 'N/A')}")
                print(f"    - 개찰일시: {item.get('opengDt', 'N/A')}")
        
        # 2. 공사 낙찰정보 조회
        print("\n" + "="*50)
        print("2. 공사 낙찰정보 조회")
        print("="*50)
        
        result2 = await service.get_bid_results(
            bid_type="construction",
            num_of_rows=3
        )
        
        body2 = result2.get("body", {})
        print(f"Total Count: {body2.get('totalCount', 0)}")
        
        items2 = body2.get("items", {})
        if isinstance(items2, dict):
            items2 = items2.get("item", [])
        
        if items2:
            for i, item in enumerate(items2[:2]):
                print(f"\n[{i+1}] {item.get('bidNtceNm', 'N/A')[:50]}")
                print(f"    - 기초금액: {item.get('asignBdgtAmt', 'N/A')}")
                print(f"    - 낙찰금액: {item.get('sucsfbidAmt', 'N/A')}")
        
        print("\n" + "="*50)
        print("API Test Complete!")
        print("="*50)
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await service.close()


if __name__ == "__main__":
    asyncio.run(test_api())
