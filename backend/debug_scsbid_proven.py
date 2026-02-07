import requests
import sys
import os
from urllib.parse import unquote
from datetime import datetime, timedelta

# Add backend to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from app.core.config import settings

def test_proven_scsbid():
    print("🕵️ Debugging Proven Scsbid Operations...")
    
    base_url = "https://apis.data.go.kr/1230000/as/ScsbidInfoService"
    key = unquote(settings.PUBLIC_DATA_KEY)
    
    # Operations found in search
    ops = [
        "getOpengResultListInfoCnstwkPPSSrch", # Construction Opening Results (PPS)
        "getScsbidListSttusThng",             # Goods Status (Just to check logic)
        "getOpengResultListInfoCnstwk"        # Maybe available here too?
    ]
    
    end_dt = datetime.now()
    start_dt = end_dt - timedelta(days=5)
    start_str = start_dt.strftime("%Y%m%d") + "0000"
    end_str = end_dt.strftime("%Y%m%d") + "2359"
    
    # Params
    params = {
        "serviceKey": key,
        "numOfRows": 5,
        "pageNo": 1,
        "inqryDiv": 1,
        "inqryBgnDt": start_str[:10], # YYYYMMDDHH format sometimes required for PPS
        "inqryEndDt": end_str[:10],
        # "type": "json" # Try XML default first
    }
    
    # PPS Search often uses YYYYMMDDHHMM or YYYYMMDD
    # Let's try regular YYYYMMDD first
    
    for op in ops:
        url = f"{base_url}/{op}"
        print(f"\n🔗 Testing: {url}")
        
        try:
            # Construct Query
            query = ""
            for k, v in params.items():
                query += f"{k}={v}&"
            
            final_url = f"{url}?{query.rstrip('&')}"
            
            res = requests.get(final_url, verify=False, timeout=10)
            print(f"   Status: {res.status_code}")
            
            if res.status_code == 200:
                print(f"   ✅ SUCCESS! Body: {res.text[:300]}")
                # Check if it has error inside
                if "<errMsg>" in res.text:
                    print(f"      Logic Error: {res.text[:200]}")
                else:
                    return # Found it!
            else:
                 print(f"   ❌ Fail. Body: {res.text[:200]}")
                 
        except Exception as e:
            print(f"   ⚠️ Exception: {e}")

if __name__ == "__main__":
    test_proven_scsbid()
