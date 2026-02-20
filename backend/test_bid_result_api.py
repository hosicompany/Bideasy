"""
낙찰정보 API 테스트 - 여러 엔드포인트 시도
"""
import requests
from datetime import datetime, timedelta

API_KEY = '22a4656cd4236b19403593956cd24357d9a27f5c3d3dcdb4b7c19fcc7a1c80a4'

# 테스트할 낙찰정보 엔드포인트들
ENDPOINTS = [
    # 낙찰정보서비스 (새 버전)
    ("BidResultInfoService", "https://apis.data.go.kr/1230000/BidResultInfoService/getBidResultListInfoCnstwkPPSSrch"),
    # 개찰결과정보
    ("ad/BidResultService", "https://apis.data.go.kr/1230000/ad/BidResultService/getScsbidListSttusServc"),
    # 낙찰정보 공사
    ("ad/BidResultInfoService", "https://apis.data.go.kr/1230000/ad/BidResultInfoService/getBidResultListInfoCnstwk"),
]

def test_endpoint(name, url):
    end_date = datetime.now().strftime("%Y%m%d")
    start_date = (datetime.now() - timedelta(days=30)).strftime("%Y%m%d")
    
    params = {
        "serviceKey": API_KEY,
        "numOfRows": 3,
        "pageNo": 1,
        "type": "json",
        "inqryBgnDt": start_date,
        "inqryEndDt": end_date,
    }
    
    print(f"\n{'='*50}")
    print(f"Testing: {name}")
    print(f"URL: {url}")
    
    try:
        response = requests.get(url, params=params, timeout=10)
        print(f"Status: {response.status_code}")
        
        if response.status_code == 200:
            try:
                data = response.json()
                header = data.get("response", {}).get("header", {})
                result_code = header.get("resultCode")
                print(f"Result: {result_code} - {header.get('resultMsg', 'N/A')}")
                
                if result_code == "00":
                    body = data.get("response", {}).get("body", {})
                    print(f"Total: {body.get('totalCount', 0)}")
                    return True
            except:
                print(f"Response (not JSON): {response.text[:200]}")
        else:
            print(f"Error: {response.text[:100]}")
    except Exception as e:
        print(f"Exception: {e}")
    
    return False

if __name__ == "__main__":
    print("Testing Bid Result APIs...")
    
    for name, url in ENDPOINTS:
        success = test_endpoint(name, url)
        if success:
            print(">>> SUCCESS!")
