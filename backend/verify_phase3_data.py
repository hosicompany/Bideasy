import sys
import os
from datetime import datetime

# Add backend to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.db.session import engine, SessionLocal
from app.db import models
from app.services.opening_result import OpeningResultService

def verify_data_collection():
    try:
        print("1. Creating Database Tables...")
        # This will create OpeningResult table if not exists
        models.Base.metadata.create_all(bind=engine)
        print("   -> Tables created/verified.")
    except Exception as e:
        print(f"❌ Database Creation Failed: {e}")
        return

    db = SessionLocal()
    
    # Try a broader search term
    agency_name = "강남구" 
    print(f"2. Crawling History for {agency_name} (1 Month)...")
    
    try:
        # Fetch 1 months history
        results_list = OpeningResultService.crawl_agency_history(agency_name, months=1)
        if not results_list:
            print("❌ No results found. Trying Mock Data insertion for DB check.")
            # Inject Mock Data manually if API fails, to verify DB Model works
            results_list = [
                {
                    "bid_no": "202499999-00",
                    "organization": "강남구청(Test)",
                    "winner_company": "테스트건설",
                    "winner_price": 50000000.0,
                    "winner_rate": 87.745,
                    "open_date": "202401011000"
                }
            ]
    except Exception as e:
        print(f"❌ Crawler Failed: {e}")
        db.close()
        return
    
    if not results_list:
        print("❌ No results found. Check crawler logic or API key.")
        return

    print(f"3. Saving {len(results_list)} results to DB...")
    
    saved_count = 0
    for item in results_list:
        # Check duplicate
        existing = db.query(models.OpeningResult).filter(
            models.OpeningResult.bid_no == item["bid_no"]
        ).first()
        
        if not existing:
            # Parse date string to object if needed, strict format is "YYYYMMDDHHMM"
            # But API sometimes returns different formats. Let's be safe.
            opendt_str = item["open_date"]
            try:
                op_date = datetime.strptime(opendt_str, "%Y%m%d%H%M")
            except:
                op_date = datetime.now()
            
            result_obj = models.OpeningResult(
                bid_no=item["bid_no"],
                organization=item["organization"],
                winner_company=item["winner_company"],
                winner_price=item["winner_price"],
                winner_rate=item["winner_rate"],
                open_date=op_date,
                crawled_at=datetime.now()
            )
            db.add(result_obj)
            saved_count += 1
            
    db.commit()
    print(f"✅ Successfully saved {saved_count} new opening results.")
    
    # Verify DB content
    count = db.query(models.OpeningResult).count()
    print(f"📊 Total OpeningResult Records in DB: {count}")
    
    db.close()

if __name__ == "__main__":
    verify_data_collection()
