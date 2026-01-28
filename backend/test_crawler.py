"""Test crawler directly with better output"""
import sys
sys.path.insert(0, '.')

from app.services.crawler import CrawlerService

print("Testing CrawlerService.fetch_notices()...")
notices = CrawlerService.fetch_notices(size=5)
print(f"\nFetched {len(notices)} notices")

if notices:
    print("\n" + "="*60)
    print("FIRST NOTICE DETAILS")
    print("="*60)
    first = notices[0]
    for key in sorted(first.keys()):
        value = first.get(key)
        if value:
            display = str(value)[:80]
            print(f"{key}: {display}")
    
    print("\n" + "="*60)
    print("EXTENDED FIELDS CHECK")
    print("="*60)
    extended_fields = [
        "organization", "demand_organization", "bid_method", 
        "contract_method", "region", "budget_amount", "opening_date",
        "international_bid", "joint_contract", "sme_only", "big_company_ok",
        "attachment_url", "attachment_name"
    ]
    for field in extended_fields:
        value = first.get(field)
        status = "✓" if value else "✗"
        print(f"  {status} {field}: {value}")
else:
    print("No notices fetched!")
