import requests
import sys
import os
from urllib.parse import unquote
from dotenv import load_dotenv

def verify_simple():
    # Setup Paths
    script_dir = os.path.dirname(os.path.abspath(__file__))
    sys.path.append(script_dir) # Ensure current dir is in path
    
    # Load .env explicitly
    env_path = os.path.join(script_dir, ".env")
    if os.path.exists(env_path):
        print(f"Loading .env from: {env_path}")
        load_dotenv(env_path)
    else:
        print(f"WARNING: .env not found at {env_path}")

    try:
        from app.core.config import settings
        raw_key = settings.PUBLIC_DATA_KEY
        print(f"Key loaded. Length: {len(raw_key)}")
        print(f"Key Start: {raw_key[:5]}... End: ...{raw_key[-5:]}")
        if " " in raw_key: print("WARNING: Key contains spaces!")
        if "%" in raw_key: print("INFO: Key contains % (Likely Encoded)")
    except Exception as e:
        print(f"Settings/Key Error: {e}")
        return

    # Try both Raw and Decoded keys
    decoded_key = unquote(raw_key)

    # 2024-01-02 (Safe date)
    date_params = {
        "numOfRows": 1,
        "pageNo": 1,
        "inqryDiv": 1,
        "opengBgnDt": "202401020000",
        "opengEndDt": "202401022359",
        "type": "json"
    }

    print(f"--- Key Probe ---")
    # Test 1: Notice (Control) - Try solving 401
    url_notice = "https://apis.data.go.kr/1230000/ad/BidPublicInfoService/getBidPblancListInfoCnstwk"
    
    # Attempt A: Raw Key
    try:
        p = date_params.copy(); p["serviceKey"] = raw_key
        # Note: requests might encode 'raw_key' again if it contains %.
        r = requests.get(url_notice, params=p, timeout=5, verify=False)
        print(f"Notice (Raw Key): {r.status_code}")
    except Exception as e: print(f"Raw Err: {e}")

    # Attempt B: Decoded Key (Recommended)
    try:
        p = date_params.copy(); p["serviceKey"] = decoded_key
        r = requests.get(url_notice, params=p, timeout=5, verify=False)
        print(f"Notice (Decoded Key): {r.status_code}")
        valid_key = decoded_key if r.status_code == 200 else raw_key
        # Note: If both fail, we have a bigger problem.
    except Exception as e: print(f"Decoded Err: {e}")

    # Use the best key for next tests? Or just try Decoded.
    best_key = decoded_key 
    
    print(f"\n--- URL Probe: Standard Scsbid Info ---")
    
    # Correct URL for Standard Opening Results (Nakchal Info)
    url = "https://apis.data.go.kr/1230000/ao/PubDataOpnStdService/getDataSetOpnStdScsbidInfo"
    
    # Correct Params for Standard Service
    # Try inqryDiv=1 (Registration Date) to get data
    params = {
        "serviceKey": best_key,
        "numOfRows": 1,
        "pageNo": 1,
        "type": "json",
        "inqryDiv": "1", # 1 = Registration Date
        "inqryBgnDt": "202401010000",
        "inqryEndDt": "202401312359",
    }
    
    try:
        r = requests.get(url, params=params, timeout=10, verify=False)
        print(f"Scsbid Status: {r.status_code}")
        
        if r.status_code == 200:
            print(f"  -> SUCCESS! Endpoint valid.")
            try:
                data = r.json().get("response", {}).get("body", {})
                items = data.get("items", [])
                total = data.get("totalCount", 0)
                print(f"  -> Total Count: {total}")
                
                if items:
                     if isinstance(items, dict): items = [items]
                     first = items[0]
                     # Print ALL keys for mapping
                     print(f"  -> First Item Keys: {list(first.keys())}")
                     print(f"  -> Sample Data: {first}")
                else:
                    print("  -> Still 0 items found.")
            except Exception as e:
                print(f"  -> JSON Parse Error: {e}")
                print(f"  -> Body: {r.text[:200]}")
        else:
            print(f"  -> FAILED. Body: {r.text[:200]}")
            
    except Exception as e:
        print(f"Scsbid Exception: {e}")

if __name__ == "__main__":
    verify_simple()
