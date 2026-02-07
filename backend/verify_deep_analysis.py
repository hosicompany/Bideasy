import requests
import json
import time

# Backend URL
BASE_URL = "http://localhost:8000/api/v1"

def find_recent_bid_with_attachments():
    print("search recent bid...")
    # 1. search recent bid
    try:
        # 1-1. try crawl
        crawl_url = f"{BASE_URL}/bids/crawl"
        print(f"calling {crawl_url} ...")
        requests.post(crawl_url, json={"keyword": "공사", "rows": 10})
        
        # 1-2. get bid list
        list_url = f"{BASE_URL}/bids/feed"
        print(f"calling {list_url} ...")
        resp = requests.get(list_url, params={"page": 1, "limit": 20})
        if resp.status_code != 200:
            print(f"failed to get bid list: {resp.status_code}")
            return None
            
        bids = resp.json()
        print(f"found {len(bids)} bids.")

        for bid in bids:
            bid_id = bid.get("bid_no") or bid.get("bidNtceNo")
            if not bid_id: continue
            
            # check attachment
            att_url = f"{BASE_URL}/analysis/{bid_id}/attachments"
            print(f"checking attachments for {bid_id}...")
            att_resp = requests.get(att_url)
            
            if att_resp.status_code == 200:
                data = att_resp.json()
                count = data.get("total_count", 0)
                print(f" -> count: {count}")
                if count > 0:
                    print(f"Found bid with attachment! ID: {bid_id} (count: {count})")
                    return bid_id
            else:
                print(f" -> failed: {att_resp.status_code}")
                    
    except Exception as e:
        print(f"Error finding bid: {e}")
        
    return None

def verify_deep_analysis(bid_id):
    deep_url = f"{BASE_URL}/analysis/{bid_id}/deep"
    print(f"\nCalling Deep Analysis for {bid_id}...")
    print(f"POST {deep_url}")
    
    try:
        # Increase timeout for AI processing
        resp = requests.post(deep_url, params={"include_raw_text": False}, timeout=120)
        
        if resp.status_code == 200:
            result = resp.json()
            print("\n✅ Analysis Success!")
            print(json.dumps(result, indent=2, ensure_ascii=False))
            
            # Check key fields
            if result.get("risk_assessment"):
                print(f"\n[Summary] Risk: {result['risk_assessment']}")
                print(f"[Summary] Comment: {result['summary']}")
            else:
                print("⚠️ Warning: Empty result fields")
                
        else:
            print(f"❌ Failed: {resp.status_code}")
            print(resp.text)
            
    except Exception as e:
        print(f"❌ Exception: {e}")

if __name__ == "__main__":
    # 1. Try to find a real bid dynamically
    target_bid = find_recent_bid_with_attachments()
    
    # 2. Fallback to a known recent ID if dynamic find fails (or takes too long)
    # Example: 20250123548-00 (You can replace this with a real one you know)
    if not target_bid:
        print("No dynamic bid found, trying fallback ID...")
        target_bid = "R25BK01253548-000" 
    
    if target_bid:
        verify_deep_analysis(target_bid)
    else:
        print("No bid ID available for testing.")
