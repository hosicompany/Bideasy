import requests

BASE_URL = "http://localhost:8000/api/v1"

def test_prediction():
    # 1. Get a valid bid_no
    try:
        feed_resp = requests.get(f"{BASE_URL}/bids/feed")
        feed_resp.raise_for_status()
        notices = feed_resp.json()
        if not notices:
            print("No notices found in feed.")
            return
        
        first_notice = notices[0]
        # print("First notice keys:", first_notice.keys())
        
        # Try snake_case if camelCase fails
        target_bid_no = first_notice.get('bidNo') or first_notice.get('bid_no')
        
        if not target_bid_no:
            print(f"Could not find bid number. Keys: {first_notice.keys()}")
            return
            
        print(f"Testing with Bid No: {target_bid_no}")
        
        # 2. Call prediction endpoint
        # Correct URL from api.py + prediction.py
        # URL has a space: "recommend points"
        url = f"{BASE_URL}/analysis/{target_bid_no}/recommend points"
        print(f"Calling: {url}")
        
        resp = requests.get(url)
        print(f"Status Code: {resp.status_code}")
        
        if resp.status_code == 200:
            data = resp.json()
            
            with open("debug_output.txt", "w", encoding="utf-8") as f:
                # Check Blue Ocean
                bo = data.get("blue_ocean", {}).get("strategies", [])
                f.write(f"Blue Ocean Strategies Count: {len(bo)}\n")
                for s in bo:
                    f.write(f" - {s['type']}: {s['reason']}\n")
                    
                # Check Monte Carlo
                mc = data.get("monte_carlo", {}).get("top_rates", [])
                f.write(f"Monte Carlo Top Rates Count: {len(mc)}\n")
                f.write(f" - Rates: {mc}\n")
            print("Debug output written to debug_output.txt")
            
        else:
            print("Error response:", resp.text)
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_prediction()
