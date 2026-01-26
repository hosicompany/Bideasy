# -*- coding: utf-8 -*-
"""Test BidDetailService directly"""
from app.services.bid_detail import BidDetailService

# Test with a real bid number
bid_no = "R25BK01250181"
bid_ord = "000"

print(f"Testing BidDetailService for: {bid_no}-{bid_ord}")
result = BidDetailService.fetch_bid_detail(bid_no, bid_ord)

if result:
    print("SUCCESS! Got bid detail:")
    print(f"  Title: {result.get('title', 'N/A')[:60]}")
    print(f"  Org: {result.get('organization', 'N/A')}")
    print(f"  Price: {result.get('estimated_price', 0):,.0f}")
    
    print("\nAnalysis Context:")
    context = BidDetailService.get_analysis_context(result)
    print(context[:500])
else:
    print("FAILED: No result returned")
