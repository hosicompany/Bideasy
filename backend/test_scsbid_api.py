"""
낙찰정보 API 테스트 - ScsbidInfoService
"""
import requests
from datetime import datetime, timedelta

API_KEY = '22a4656cd4236b19403593956cd24357d9a27f5c3d3dcdb4b7c19fcc7a1c80a4'
BASE_URL = "https://apis.data.go.kr/1230000/as/ScsbidInfoService"

# 가능한 엔드포인트들 테스트
ENDPOINTS = [
    "getScsbidListSttusInfo",      # 낙찰현황목록
    "getScsbidListSttusServc",     # 낙찰현황-용역
    "getScsbidListSttusCnstwk",    # 낙찰현황-공사
    "getScsbidListSttusThng",      # 낙찰현황-물품
]

def test_endpoint(endpoint):
    url = f"{BASE_URL}/{endpoint}"
    
    end_date = datetime.now().strftime("%Y%m%d")
    start_date = (datetime.now() - timedelta(days=30)).strftime("%Y%m%d")
    
    params = {
        "serviceKey": API_KEY,
        "numOfRows": 5,
        "pageNo": 1,
        "type": "json",
        "inqryBgnDt": start_date,
        "inqryEndDt": end_date,
    }
    
    print(f"\n{'='*50}")
    print(f"Testing: {endpoint}")
    print(f"URL: {url}")
    
    try:
        response = requests.get(url, params=params, timeout=15)
        print(f"Status: {response.status_code}")
        
        if response.status_code == 200:
            try:
                data = response.json()
                header = data.get("response", {}).get("header", {})
                result_code = header.get("resultCode")
                print(f"Result: {result_code} - {header.get('resultMsg', 'N/A')}")
                
                if result_code == "00":
                    body = data.get("response", {}).get("body", {})
                    total = body.get("totalCount", 0)
                    print(f"Total Count: {total}")
                    
                    items = body.get("items", [])
                    if isinstance(items, dict):
                        items = [items]
                    
                    if items and len(items) > 0:
                        print(f"Found {len(items)} items!")
                        for i, item in enumerate(items[:3]):
                            print(f"\n[{i+1}]")
                            # Print available keys
                            for key in list(item.keys())[:10]:
                                val = str(item.get(key, ""))[:50]
                                print(f"    {key}: {val}")
                        return True, items
            except Exception as e:
                print(f"Parse Error: {e}")
                print(f"Response: {response.text[:300]}")
        else:
            print(f"Error: {response.text[:200]}")
    except Exception as e:
        print(f"Exception: {e}")
    
    return False, []

if __name__ == "__main__":
    print("Testing ScsbidInfoService API...")
    print(f"Base URL: {BASE_URL}")
    
    success_endpoints = []
    for endpoint in ENDPOINTS:
        success, items = test_endpoint(endpoint)
        if success:
            success_endpoints.append(endpoint)
            print(">>> SUCCESS!")
    
    print(f"\n{'='*50}")
    print(f"Working Endpoints: {success_endpoints}")
