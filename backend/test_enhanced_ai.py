"""Test enhanced AI analysis with rule-based tips"""
import requests
import json

base_url = "http://localhost:8000"

print("=" * 70)
print("ENHANCED AI ANALYSIS TEST")
print("=" * 70)

bid_no = "TEST-002"

params = {
    "title": "경북대학교 IT대학 1호관 강의실여건개선 및 내부도어 교체공사",
    "basic_price": "85000000",
    "organization": "경북대학교",
    "demand_organization": "시설과",
    "contract_type": "CONSTRUCTION",
    "bid_method": "전자입찰",
    "contract_method": "일반경쟁입찰",
    "region": "대구광역시",
    "budget_amount": "90000000",
    "opening_date": "2026-02-05 10:00",
    "international_bid": "N",
    "joint_contract": "Y",
    "sme_only": "Y",
    "big_company_ok": "N",
    "emergency_bid": "N",
    "rebid_yn": "N",
    "attachment_url": "https://www.g2b.go.kr/pn/pnp/pnpe/UntyAtchFile/download",
    "attachment_name": "공고규격서.hwp",
    "start_date": "2026-01-20T00:00:00",
    "end_date": "2026-02-04T18:00:00"
}

print(f"\nEndpoint: /api/v1/ai/{bid_no}/analysis")

print("\nCalling Enhanced AI Analysis API...")
try:
    response = requests.get(
        f"{base_url}/api/v1/ai/{bid_no}/analysis", 
        params=params, 
        timeout=30
    )
    print(f"Status: {response.status_code}")
    
    if response.status_code == 200:
        data = response.json()
        
        # Save full result
        with open("enhanced_analysis_result.json", "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        print("\n" + "=" * 70)
        print("ANALYSIS RESULT")
        print("=" * 70)
        
        # Summary
        print("\n[Summary]")
        print(f"  {data.get('summary', 'N/A')}")
        
        # Eligibility
        eligibility = data.get('eligibility', {})
        print("\n[Eligibility]")
        print(f"  Requirements: {eligibility.get('requirements', [])}")
        
        # Deadline Info
        deadline = data.get('deadline_info', {})
        print("\n[Deadline Info]")
        print(f"  Days Remaining: {deadline.get('days_remaining')}")
        print(f"  Is Urgent: {deadline.get('is_urgent')}")
        
        # Price Info
        price = data.get('price_info', {})
        print("\n[Price Info]")
        print(f"  Basic Price: {price.get('basic_price_formatted')}")
        lower = price.get('lower_limit', {})
        print(f"  Lower Limit: {lower.get('rate')}% = {lower.get('formatted')}")
        
        # Tips
        tips = data.get('tips', [])
        print(f"\n[Tips] ({len(tips)} items)")
        for i, tip in enumerate(tips, 1):
            importance = tip.get('importance', 'LOW')
            icon = tip.get('icon', '')
            title = tip.get('title', '')
            source = tip.get('source', '')
            has_beginner = bool(tip.get('for_beginners'))
            
            print(f"\n  {i}. {icon} [{importance}] {title}")
            print(f"     Source: {source}")
            print(f"     Has Beginner Explanation: {has_beginner}")
        
        print("\n" + "=" * 70)
        print("SUCCESS! Full result saved to: enhanced_analysis_result.json")
        print("=" * 70)
    else:
        print(f"Error: {response.text[:500]}")
        
except Exception as e:
    print(f"Error: {type(e).__name__}: {e}")
