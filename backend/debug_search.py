"""Debug script for Smart Search API testing"""
import requests
import json

# Test the Public Data API directly
BASE_URL = "https://apis.data.go.kr/1230000/ad/BidPublicInfoService/getBidPblancListInfoCnstwk"

# Load API key from .env
from dotenv import load_dotenv
import os
load_dotenv()
API_KEY = os.getenv("PUBLIC_DATA_KEY")

def test_search(param_name, param_value, size=5):
    """Test API with specific parameter"""
    from datetime import datetime, timedelta
    
    end_date = datetime.now().strftime("%Y%m%d") + "2359"
    start_date = (datetime.now() - timedelta(days=30)).strftime("%Y%m%d") + "0000"
    
    params = {
        "serviceKey": API_KEY,
        "numOfRows": size,
        "pageNo": 1,
        "inqryDiv": 1,
        "inqryBgnDt": start_date,
        "inqryEndDt": end_date,
        "type": "json"
    }
    
    if param_value:
        params[param_name] = param_value
    
    print(f"\n=== Testing {param_name}={param_value} ===")
    response = requests.get(BASE_URL, params=params)
    
    if response.status_code != 200:
        print(f"Error: {response.status_code}")
        return
    
    try:
        data = response.json()
        items = data.get("response", {}).get("body", {}).get("items", [])
        if isinstance(items, dict):
            items = [items]
        
        print(f"Found {len(items)} items:")
        for item in items[:5]:
            org = item.get("ntceInsttNm", "N/A")
            title = item.get("bidNtceNm", "N/A")[:50]
            print(f"  - [{org}] {title}")
    except Exception as e:
        print(f"Parse error: {e}")

if __name__ == "__main__":
    # Test 1: Region search with ntceInsttNm
    test_search("ntceInsttNm", "부산")
    
    # Test 2: Keyword search with bidNtceNm
    test_search("bidNtceNm", "전기")
    
    # Test 3: No filter (default)
    test_search("none", None)
