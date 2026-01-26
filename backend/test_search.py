"""Automated Search Testing Script"""
import requests
import json
from urllib.parse import quote

BASE_URL = "http://127.0.0.1:8000/api/v1/bids/feed"

def test_search(keyword, expected_in_title_or_org, description):
    """Test search and verify results contain expected keyword"""
    print(f"\n{'='*60}")
    print(f"TEST: {description}")
    print(f"Keyword: '{keyword}'")
    print(f"Expected: Results should contain '{expected_in_title_or_org}'")
    print(f"{'='*60}")
    
    try:
        encoded_keyword = quote(keyword)
        response = requests.get(f"{BASE_URL}?keyword={encoded_keyword}", timeout=30)
        
        if response.status_code != 200:
            print(f"❌ FAIL: HTTP {response.status_code}")
            return False
        
        data = response.json()
        print(f"Total results: {len(data)}")
        
        if len(data) == 0:
            print(f"❌ FAIL: No results returned")
            return False
        
        # Check how many results contain the expected keyword
        matches = 0
        for item in data:
            title = item.get("title", "").lower()
            # For now, just check title
            if expected_in_title_or_org.lower() in title:
                matches += 1
        
        match_rate = (matches / len(data)) * 100
        print(f"Matches: {matches}/{len(data)} ({match_rate:.1f}%)")
        
        # Show first 5 results
        print(f"\nFirst 5 results:")
        for i, item in enumerate(data[:5]):
            title = item.get("title", "N/A")[:60]
            print(f"  {i+1}. {title}")
        
        if match_rate >= 50:
            print(f"\n✅ PASS: {match_rate:.1f}% of results match expected keyword")
            return True
        else:
            print(f"\n⚠️ LOW MATCH: Only {match_rate:.1f}% of results match")
            return False
            
    except Exception as e:
        print(f"❌ ERROR: {e}")
        return False

if __name__ == "__main__":
    results = []
    
    # Test 1: Region search
    results.append(test_search("부산", "부산", "Region Search - Busan"))
    
    # Test 2: Keyword search
    results.append(test_search("전기", "전기", "Keyword Search - Electrical"))
    
    # Test 3: Another keyword
    results.append(test_search("도로", "도로", "Keyword Search - Road"))
    
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    passed = sum(results)
    total = len(results)
    print(f"Passed: {passed}/{total}")
    
    if passed == total:
        print("🎉 All tests passed!")
    else:
        print("⚠️ Some tests failed. Check logs above.")
