"""Test API endpoint with detailed logging"""
import requests

# Test 1: Without keyword (default feed)
print("="*60)
print("Test 1: Default feed (no keyword)")
print("="*60)
r = requests.get("http://localhost:8000/api/v1/bids/feed", timeout=60)
print(f"Status: {r.status_code}")
if r.status_code == 200:
    data = r.json()
    items = data if isinstance(data, list) else data.get("items", [])
    print(f"Items count: {len(items)}")
    if items:
        print(f"First item title: {items[0].get('title', 'N/A')[:50]}")
        # Check extended fields
        first = items[0]
        print("\nExtended fields in first item:")
        print(f"  organization: {first.get('organization')}")
        print(f"  bid_method: {first.get('bid_method')}")
        print(f"  contract_method: {first.get('contract_method')}")
        print(f"  attachment_url: {first.get('attachment_url', '')[:50]}...")

# Test 2: With keyword "공사"
print("\n" + "="*60)
print("Test 2: Keyword search '공사'")
print("="*60)
r = requests.get("http://localhost:8000/api/v1/bids/feed", params={"keyword": "공사"}, timeout=60)
print(f"Status: {r.status_code}")
if r.status_code == 200:
    data = r.json()
    items = data if isinstance(data, list) else data.get("items", [])
    print(f"Items count: {len(items)}")
    if items:
        print(f"First item title: {items[0].get('title', 'N/A')[:50]}")
