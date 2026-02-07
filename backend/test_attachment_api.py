import requests
import os

# Load .env manually
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
URL = "https://apis.data.go.kr/1230000/PubDataOpnStdService/getDataSetOpnStdBidPblancAtchFileInfo"

def test_attachment(bid_no_input):
    print(f"\nTesting with bidNtceNo='{bid_no_input}' ...")
    params = {
        "serviceKey": API_KEY,
        "numOfRows": 10,
        "pageNo": 1,
        "type": "json",
        "bidNtceNo": bid_no_input,
    }
    
    try:
        resp = requests.get(URL, params=params)
        if resp.status_code == 200:
            data = resp.json()
            items = data.get("response", {}).get("body", {}).get("items", [])
            print(f" -> Found {len(items) if isinstance(items, list) else 1} items")
            if items:
                print(f"    (First item: {items[0] if isinstance(items, list) else items})")
        else:
            print(f" -> Failed: {resp.status_code}")
    except Exception as e:
        print(f" -> Error: {e}")

if __name__ == "__main__":
    if not API_KEY:
        print("No API Key found")
    else:
        # 1. Full Format
        test_attachment("R25BK01253548-000")
        
        # 2. Clean Format (Split)
        test_attachment("R25BK01253548")
