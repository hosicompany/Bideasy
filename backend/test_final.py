# -*- coding: utf-8 -*-
"""Final Automated Search Test"""
import requests
from urllib.parse import quote

BASE_URL = "http://127.0.0.1:8000/api/v1/bids/feed"

def test():
    keywords = [
        ("busan", "%EB%B6%80%EC%82%B0"),  # 부산 pre-encoded
        ("electric", "%EC%A0%84%EA%B8%B0"),  # 전기 pre-encoded
        ("road", "%EB%8F%84%EB%A1%9C"),  # 도로 pre-encoded
    ]
    
    all_pass = True
    
    for name, encoded_kw in keywords:
        r = requests.get(f"{BASE_URL}?keyword={encoded_kw}", timeout=30)
        if r.status_code == 200:
            data = r.json()
            count = len(data)
            if count > 0:
                print(f"[PASS] {name}: {count} results")
                print(f"       First: {data[0].get('title', 'N/A')[:60]}")
            else:
                print(f"[WARN] {name}: 0 results (no matches)")
                all_pass = False
        else:
            print(f"[FAIL] {name}: HTTP {r.status_code}")
            all_pass = False
    
    print()
    if all_pass:
        print("All tests passed!")
    else:
        print("Some tests failed or returned no results.")

if __name__ == "__main__":
    test()
