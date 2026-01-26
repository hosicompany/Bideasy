# -*- coding: utf-8 -*-
"""Debug scraper to see raw response"""
import requests
from bs4 import BeautifulSoup

url = "https://www.g2b.go.kr/link/PNPE027_01/single/?bidPbancNo=R25BK01250181&bidPbancOrd=000"

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

print(f"Fetching: {url}")
response = requests.get(url, headers=headers, verify=False, timeout=30)
print(f"Status: {response.status_code}")
print(f"Content-Type: {response.headers.get('Content-Type', 'N/A')}")
print(f"Response length: {len(response.text)} chars")

# Show first 1000 chars of raw HTML
print("\n--- Raw HTML (first 1000 chars) ---")
print(response.text[:1000])

# Try parsing
soup = BeautifulSoup(response.text, 'html.parser')
if soup.body:
    body_text = soup.body.get_text(separator="\n", strip=True)
    print(f"\n--- Body text length: {len(body_text)} ---")
    print(body_text[:500])
else:
    print("No body found")
