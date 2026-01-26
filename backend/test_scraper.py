# -*- coding: utf-8 -*-
"""Test scraper on G2B URL"""
from app.services.scraper import ScraperService

url = "https://www.g2b.go.kr/link/PNPE027_01/single/?bidPbancNo=R25BK01250181&bidPbancOrd=000"
print(f"Testing URL: {url}")

content = ScraperService.fetch_page_content(url)
print(f"Content length: {len(content)} chars")

if content:
    print("First 500 chars:")
    print(content[:500])
else:
    print("EMPTY CONTENT RETURNED")
