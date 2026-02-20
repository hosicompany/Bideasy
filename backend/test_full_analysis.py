# -*- coding: utf-8 -*-
"""Test comprehensive AI analysis with extended fields"""
import requests

url = "http://127.0.0.1:8000/api/v1/ai/TEST-FULL-001/analysis"

# Simulate full bid data from crawler
params = {
    "title": "\ubd80\uc0b0\uad11\uc5ed\uc2dc \uae30\uc7a5\uad70 \uccad\uc0ac \ub9ac\ubaa8\ub378\ub9c1 \uacf5\uc0ac",  # 부산광역시 기장군 청사 리모델링 공사
    "basic_price": "830990000",
    "organization": "\ubd80\uc0b0\uad11\uc5ed\uc2dc \uae30\uc7a5\uad70",  # 부산광역시 기장군
    "demand_organization": "\uae30\uc7a5\uad70\uccad",  # 기장군청
    "bid_method": "\uc804\uc790\uc785\ucc30",  # 전자입찰
    "contract_method": "\uc77c\ubc18\uacbd\uc7c1\uc785\ucc30",  # 일반경쟁입찰
    "bid_type": "\uacf5\uc0ac",  # 공사
    "status": "\uc77c\ubc18\uacf5\uace0",  # 일반공고
    "region": "\ubd80\uc0b0\uad11\uc5ed\uc2dc",  # 부산광역시
    "budget_amount": "900000000",
    "opening_date": "2026-01-30 14:00",
    "international_bid": "N",
    "joint_contract": "Y",
    "sme_only": "Y",
    "big_company_ok": "N",
    "emergency_bid": "N",
    "rebid_yn": "N",
    "attachment_url": "https://www.g2b.go.kr/file/example.pdf",
    "attachment_name": "\uacf5\uace0\uaddc\uaca9\uc11c.pdf",  # 공고규격서.pdf
    "start_date": "2026-01-25T09:00:00",
    "end_date": "2026-01-29T18:00:00",
}

print("Testing AI Analysis API with comprehensive data...")
print(f"Title: {params['title']}")
print(f"Organization: {params['organization']}")
print(f"Region: {params.get('region', 'N/A')}")
print(f"SME Only: {params.get('sme_only', 'N/A')}")
print()

response = requests.get(url, params=params, timeout=60)

print(f"Status: {response.status_code}")
if response.status_code == 200:
    data = response.json()
    print("\nSUCCESS! AI Analysis Result:")
    print(f"  Badges: {data.get('badges', [])}")
    print(f"  Check Items ({len(data.get('check_items', []))}):")
    for item in data.get('check_items', [])[:5]:
        print(f"    - [{item.get('status')}] {item.get('label')}: {item.get('text')[:50]}...")
    print(f"  Tips ({len(data.get('tips', []))}):")
    for tip in data.get('tips', [])[:3]:
        print(f"    - {tip[:60]}...")
else:
    print(f"Error: {response.text}")
