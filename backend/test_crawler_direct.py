import requests
from datetime import datetime, timedelta

# Load .env manually to avoid dependency issues
def load_env():
    try:
        with open(".env", "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("PUBLIC_DATA_KEY="):
                    return line.split("=", 1)[1].strip()
    except:
        pass
    return None

API_KEY = load_env()
# Clean the key (url decode if needed, but requests usually handles it if passed as param?? NO, serviceKey needs special handling)
# Usually serviceKey from portal is already encoded or decoded. 
# We try sending it AS IS first.

URL = "https://apis.data.go.kr/1230000/ad/BidPublicInfoService/getBidPblancListInfoCnstwk"

def test_api():
    if not API_KEY:
        print("❌ No PUBLIC_DATA_KEY found in .env")
        return

    print(f"🔑 Testing with Key: {API_KEY[:10]}...")
    
    # Params
    end_date = datetime.now()
    start_date = end_date - timedelta(days=30)
    
    params = {
        "serviceKey": API_KEY, # requests might url-encode this again. Known issue.
        "numOfRows": 5,
        "pageNo": 1,
        "inqryDiv": 1,
        "inqryBgnDt": start_date.strftime("%Y%m%d0000"),
        "inqryEndDt": end_date.strftime("%Y%m%d2359"),
        "type": "json"
    }
    
    # IMPORTANT: serviceKey double encoding issue in Python requests
    # We construct query string manually for serviceKey to be safe
    try:
        # standard request
        print("\n1. Standard Request...")
        resp = requests.get(URL, params=params)
        print(f"Status: {resp.status_code}")
        print(f"Content: {resp.text[:500]}") # Print first 500 chars
        
        if "<OpenAPI_ServiceResponse>" in resp.text:
            print(" -> XML Error Response detected.")
        else:
            data = resp.json()
            items = data.get("response", {}).get("body", {}).get("items", [])
            if items:
                first_item = items[0] if isinstance(items, list) else items
                print("\n[Item Keys]:", first_item.keys())
                print(f"\n[Attachment URL]: {first_item.get('ntceSpecDocUrl1', 'Not Found')}")
                print(f"[Attachment Name]: {first_item.get('ntceSpecFileNm1', 'Not Found')}")
            else:
                print("No items found.")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_api()
