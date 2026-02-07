import requests
import sys
import os
from urllib.parse import unquote, quote
from datetime import datetime, timedelta

# Add backend to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from app.core.config import settings

def test_api_configurations():
    print("🕵️ Starting Comprehensive API Debug (Fixed)...")
    
    # 1. Setup Base Data
    raw_key = settings.PUBLIC_DATA_KEY
    decoded_key = unquote(raw_key) 
    
    keys_to_test = {
        "RAW_FROM_ENV": raw_key,
        "DECODED": decoded_key
    }
    
    # Standard Date
    end_dt = datetime.now()
    start_dt = end_dt - timedelta(days=5)
    start_str = start_dt.strftime("%Y%m%d") + "0000"
    end_str = end_dt.strftime("%Y%m%d") + "2359"
    
    # Endpoints to test
    endpoints = [
        # Construction Opening Results
        "http://apis.data.go.kr/1230000/BidPublicInfoService04/getOpengResultListInfoCnstwk",
        # Notice List (To verify general permission)
        "http://apis.data.go.kr/1230000/BidPublicInfoService04/getBidPblancListInfoCnstwk"
    ]
    
    for url in endpoints:
        print(f"\n🔗 Testing Endpoint: {url}")
        
        is_notice = "getBidPblancListInfo" in url
        
        for key_name, key_val in keys_to_test.items():
            print(f"   🔑 Testing Key: {key_name}")
            
            # Base Params
            params = {
                "numOfRows": 1,
                "pageNo": 1,
                "inqryDiv": 1,
                "type": "json" 
            }
            
            # Date Params
            if is_notice:
                params["inqryBgnDt"] = start_str[:8]
                params["inqryEndDt"] = end_str[:8]
            else:
                params["opengBgnDt"] = start_str
                params["opengEndDt"] = end_str
            
            try:
                # Manual URL Construction to avoid double-encoding issues
                base_query = ""
                for k, v in params.items():
                    base_query += f"&{k}={v}"
                
                # Append Service Key manually
                final_url = f"{url}?serviceKey={key_val}{base_query}"
                
                # print(f"      -> GET {final_url}")
                
                # Verify=False to ignore SSL cert issues (common in KR gov sites)
                res = requests.get(final_url, timeout=10, verify=False)
                
                status = res.status_code
                body = res.text
                
                if status == 200:
                    # check for logical XML errors hidden in 200
                    if "<errMsg>" in body:
                         print(f"      ❌ 200 OK but Logic Error: {body[:200]}")
                    elif "SERVICE_KEY_IS_NOT_REGISTERED_ERROR" in body:
                         print(f"      ❌ 200 OK but Key Not Registered")
                    else:
                        print(f"      ✅ SUCCESS! (Status: 200)")
                        print(f"      📝 Sample: {body[:100]}...")
                        return # Stop if found working
                else:
                    print(f"      ❌ Status: {status}")
                    print(f"      📄 Body: {body[:500]}") # Print body to diagnose 500
                    
            except Exception as e:
                print(f"      ⚠️ Exception: {e}")

    print("\n🏁 Debug Complete. Check outputs above.")

if __name__ == "__main__":
    test_api_configurations()
