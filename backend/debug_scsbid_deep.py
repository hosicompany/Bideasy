import requests
import sys
import os
from urllib.parse import unquote
from datetime import datetime, timedelta

# Add backend to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from app.core.config import settings

def test_deep_scsbid():
    print("🕵️ Debugging 401/500 Details...")
    
    base_url = "https://apis.data.go.kr/1230000/as/ScsbidInfoService"
    key = unquote(settings.PUBLIC_DATA_KEY)
    
    ops = [
        "getOpengResultListInfoCnstwkPPSSrch", 
        "getScsbidListInfoCnstwk" # Try this common pattern too
    ]
    
    params = {
        "serviceKey": key,
        "numOfRows": 1,
        "pageNo": 1,
        "inqryDiv": 1,
        "inqryBgnDt": (datetime.now() - timedelta(days=5)).strftime("%Y%m%d") + "0000",
        "inqryEndDt": datetime.now().strftime("%Y%m%d") + "2359",
    }
    
    for op in ops:
        url = f"{base_url}/{op}"
        print(f"\n🔗 Testing: {url}")
        
        try:
            # Manual Query Construction
            query = f"serviceKey={key}"
            for k, v in params.items():
                if k == "serviceKey": continue
                query += f"&{k}={v}"
            
            final_url = f"{url}?{query}"
            
            res = requests.get(final_url, verify=False, timeout=10)
            print(f"   Status: {res.status_code}")
            print(f"   Body: {res.text[:1000]}") # Print FULL body
                 
        except Exception as e:
            print(f"   ⚠️ Exception: {e}")

if __name__ == "__main__":
    test_deep_scsbid()
