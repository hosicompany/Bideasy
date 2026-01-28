"""Test AI Analysis API with extended fields - UTF-8 safe"""
import requests
import json
import sys

base_url = "http://localhost:8000"

# Force UTF-8 for console
sys.stdout.reconfigure(encoding='utf-8')

print("="*70)
print("AI ANALYSIS API TEST")
print("="*70)

bid_no = "TEST-001"

params = {
    "title": "경북대학교 IT대학 1호관 강의실여건개선 및 내부도어 교체공사",
    "basic_price": "85000000",
    "organization": "경북대학교",
    "demand_organization": "시설과",
    "bid_method": "전자입찰",
    "contract_method": "일반경쟁입찰",
    "region": "대구광역시",
    "budget_amount": "90000000",
    "opening_date": "2026-02-05 10:00",
    "international_bid": "N",
    "joint_contract": "Y",
    "sme_only": "Y",
    "big_company_ok": "N",
    "attachment_url": "https://www.g2b.go.kr/pn/pnp/pnpe/UntyAtchFile/download",
    "attachment_name": "공고규격서.hwp",
    "start_date": "2026-01-20T00:00:00",
    "end_date": "2026-02-04T18:00:00"
}

print(f"\nEndpoint: /api/v1/ai/{bid_no}/analysis")

print("\nCalling AI Analysis API...")
try:
    response = requests.get(f"{base_url}/api/v1/ai/{bid_no}/analysis", params=params, timeout=120)
    print(f"\nStatus: {response.status_code}")
    
    if response.status_code == 200:
        data = response.json()
        print("\n" + "="*70)
        print("AI ANALYSIS RESULT")
        print("="*70)
        
        # Save to file for proper viewing
        with open("ai_result.json", "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        # Print summary
        summary = data.get("summary", [])
        print("\n[Summary]:")
        for i, line in enumerate(summary, 1):
            # Remove emojis for console compatibility
            clean_line = ''.join(c for c in str(line) if ord(c) < 0x10000)
            print(f"  {i}. {clean_line}")
        
        # Print risks
        risks = data.get("risks", [])
        print(f"\n[Risks] ({len(risks)} items):")
        for risk in risks:
            level = risk.get("level", "UNKNOWN")
            rtype = risk.get("type", "N/A")
            content = risk.get("content", "N/A")
            # Clean emojis
            clean_content = ''.join(c for c in str(content) if ord(c) < 0x10000)
            print(f"  [{level}] {rtype}: {clean_content[:80]}")
            
        print("\n[SUCCESS] AI analysis completed!")
        print("Full result saved to: ai_result.json")
    else:
        print(f"Error: {response.text[:500]}")
        
except Exception as e:
    print(f"Error: {type(e).__name__}: {e}")
