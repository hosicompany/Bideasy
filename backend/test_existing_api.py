"""
기존 API 엔드포인트 테스트
"""
import requests
from datetime import datetime, timedelta

API_KEY = '22a4656cd4236b19403593956cd24357d9a27f5c3d3dcdb4b7c19fcc7a1c80a4'

# 기존 크롤러에서 사용하던 엔드포인트
BASE_URL = "https://apis.data.go.kr/1230000/ad/BidPublicInfoService/getBidPblancListInfoCnstwk"

def test_api():
    end_date = datetime.now().strftime("%Y%m%d") + "2359"
    start_date = (datetime.now() - timedelta(days=30)).strftime("%Y%m%d") + "0000"
    
    params = {
        "serviceKey": API_KEY,
        "numOfRows": 5,
        "pageNo": 1,
        "inqryDiv": 1,
        "inqryBgnDt": start_date,
        "inqryEndDt": end_date,
        "type": "json"
    }
    
    print("Testing BidPublicInfoService API...")
    print(f"URL: {BASE_URL}")
    print(f"Date Range: {start_date} ~ {end_date}")
    
    response = requests.get(BASE_URL, params=params)
    print(f"Status: {response.status_code}")
    
    if response.status_code == 200:
        try:
            data = response.json()
            header = data.get("response", {}).get("header", {})
            print(f"Result Code: {header.get('resultCode')}")
            print(f"Result Msg: {header.get('resultMsg')}")
            
            body = data.get("response", {}).get("body", {})
            total = body.get("totalCount", 0)
            print(f"Total Count: {total}")
            
            items = body.get("items", [])
            if isinstance(items, dict):
                items = [items]
            
            if items:
                print(f"\nFound {len(items)} items!")
                for i, item in enumerate(items[:3]):
                    print(f"\n[{i+1}] {item.get('bidNtceNm', 'N/A')[:50]}")
                    print(f"    No: {item.get('bidNtceNo')}-{item.get('bidNtceOrd')}")
                    print(f"    Price: {item.get('presmptPrce', 'N/A')}")
                print("\nSUCCESS!")
            else:
                print("No items")
        except Exception as e:
            print(f"Parse Error: {e}")
            print(f"Response: {response.text[:500]}")
    else:
        print(f"Error: {response.text[:300]}")

if __name__ == "__main__":
    test_api()
