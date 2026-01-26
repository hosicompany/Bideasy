# -*- coding: utf-8 -*-
"""Test AI Analysis API with query parameters"""
import requests
from urllib.parse import quote

url = "http://127.0.0.1:8000/api/v1/ai/TEST-001/analysis"
params = {
    "title": "부산광역시 기장군 청사 리모델링 공사",
    "basic_price": "830990000"
}

print(f"Testing AI Analysis API with query params...")
print(f"Title: {params['title']}")
print(f"Basic Price: {params['basic_price']}")

response = requests.get(url, params=params, timeout=60)

print(f"\nStatus: {response.status_code}")
if response.status_code == 200:
    print("SUCCESS! AI Analysis returned:")
    data = response.json()
    print(f"  Badges: {data.get('badges', [])}")
    print(f"  Check Items: {len(data.get('check_items', []))} items")
    print(f"  Tips: {len(data.get('tips', []))} tips")
else:
    print(f"Error: {response.text}")
