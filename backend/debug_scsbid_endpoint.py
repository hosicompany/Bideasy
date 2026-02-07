import requests
import sys
import os
from urllib.parse import unquote
from datetime import datetime, timedelta

# Add backend to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from app.core.config import settings

def test_scsbid_endpoint():
    print("🕵️ Debugging New Endpoint: ScsbidInfoService")
    
    # 1. Base URL provided by User
    base_url = "https://apis.data.go.kr/1230000/as/ScsbidInfoService"
    
    # 2. Key
    key = unquote(settings.PUBLIC_DATA_KEY)
    print(f"🔑 Key Sample: {key[:10]}...")
    
    # 3. Operations to Guess/Try
    # "낙찰정보서비스" usually has:
    # getScsbidListInfoCnstwk (Construction)
    # getScsbidListInfoServc (Service)
    # getScsbidListInfoThng (Goods)
    
    ops = [
        "getScsbidListInfoCnstwk", 
        "getScsbidListInfo" # sometimes generic
    ]
    
    # Date Range
    end_dt = datetime.now()
    start_dt = end_dt - timedelta(days=5)
    
    start_str = start_dt.strftime("%Y%m%d") + "0000"
    end_str = end_dt.strftime("%Y%m%d") + "2359"
    
    params = {
        "serviceKey": key,
        "numOfRows": 10,
        "pageNo": 1,
        "inqryDiv": 1,
        "inqryBgnDt": start_str[:10], # standard search param
        "inqryEndDt": end_str[:10],
        # "type": "json" # Try without first (XML default)
    }
    
    for op in ops:
        # User provided 'https://apis.data.go.kr/1230000/as/ScsbidInfoService'
        # Usually it structure is: BASE / OPERATION
        # But 'as' in path is weird. 
        # Standard: apis.data.go.kr/1230000/ScsbidInfoService/getScsbidListInfoCnstwk
        
        # Let's try User's exact path + operation
        # AND Standard path + operation
        
        urls_to_try = [
            f"{base_url}/{op}", # User path + op
            f"http://apis.data.go.kr/1230000/ScsbidInfoService/{op}" # Standard path + op
        ]
        
        for url in urls_to_try:
            print(f"\n🔗 Trying: {url}")
            try:
                # Construct query manually
                query = "&".join([f"{k}={v}" for k, v in params.items()])
                final_url = f"{url}?{query}"
                
                res = requests.get(final_url, verify=False, timeout=10)
                
                print(f"   Status: {res.status_code}")
                if res.status_code == 200:
                    print(f"   ✅ SUCCESS! Body: {res.text[:300]}")
                    return
                else:
                     print(f"   ❌ Fail. Body: {res.text[:100]}")
                     
            except Exception as e:
                print(f"   ⚠️ Exception: {e}")
                
if __name__ == "__main__":
    test_scsbid_endpoint()
