# -*- coding: utf-8 -*-
"""Debug script for filtering logic"""
from app.services.crawler import CrawlerService

def test_filtering():
    keyword = "\ubd80\uc0b0"  # 부산 in unicode
    is_region = CrawlerService.is_region_keyword(keyword)
    print(f"Keyword: {keyword}")
    print(f"Is region: {is_region}")
    
    print("Fetching 500 items...")
    results = CrawlerService.fetch_notices(size=500)
    print(f"Fetched: {len(results)}")
    
    # Filtering
    keyword_lower = keyword.lower()
    filtered = []
    for item in results:
        title = item.get("title", "").lower()
        org = item.get("organization", "").lower()
        if is_region:
            if keyword_lower in org or keyword_lower in title:
                filtered.append(item)
        else:
            if keyword_lower in title:
                filtered.append(item)
    
    print(f"Filtered: {len(filtered)}")
    for item in filtered[:5]:
        print(f"  - [{item.get('organization', 'N/A')[:20]}] {item.get('title', 'N/A')[:40]}")

if __name__ == "__main__":
    test_filtering()
