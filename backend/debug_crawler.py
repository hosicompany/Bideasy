# -*- coding: utf-8 -*-
from app.services.crawler import CrawlerService

print("Testing CrawlerService.crawl_bids('부산')...")
try:
    results = CrawlerService.fetch_notices(keyword="부산")
    print(f"Items found: {len(results)}")
    
    if results:
        first_item = results[0]
        print("\nFirst Item Keys:")
        print(list(first_item.keys()))
        print("\nSample Data:")
        for k, v in first_item.items():
            print(f"{k}: {v}")
            
        # Verify against Notice model columns (Mock check)
        from app.db.models import Notice
        model_cols = [c.name for c in Notice.__table__.columns]
        print(f"\nModel Columns: {len(model_cols)}")
        
        missing_in_model = [k for k in first_item.keys() if k not in model_cols]
        print(f"Keys not in Model: {missing_in_model}")
        
    else:
        print("No results returned from API.")

except Exception as e:
    print(f"Error: {e}")
