import sys
import os
import time
from datetime import datetime, timedelta
import requests
from dotenv import load_dotenv

# Add backend to path logic (existing)
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Explicitly load .env BEFORE other app imports
env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.exists(env_path):
    load_dotenv(env_path)

from app.db.session import SessionLocal, engine
from app.db import models
from app.core.config import settings

def crawl_nationwide_history(months: int = 12):
    """
    Crawl ALL opening results for the past N months.
    """
    if settings.PUBLIC_DATA_KEY:
        print(f"🔑 Key loaded! Length: {len(settings.PUBLIC_DATA_KEY)}")
    else:
        print("❌ WARNING: API Key is EMPTY!")
    
    # Ensure tables exist
    models.Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    
    # Updated to Standard Scsbid Endpoint (200 OK)
    base_url = "https://apis.data.go.kr/1230000/ao/PubDataOpnStdService/getDataSetOpnStdScsbidInfo"
    
    print(f"🚀 Starting Nationwide Crawl for last {months} months...")
    print(f"🌍 Endpoint: {base_url}")
    
    total_saved = 0
    start_time = time.time()
    
    for i in range(months):
        # Calculate Date Range for this month chunk
        target_date = datetime.now() - timedelta(days=30 * i)
        end_dt = target_date
        start_dt = target_date - timedelta(days=29) 
        
        start_str = start_dt.strftime("%Y%m%d") + "0000"
        end_str = end_dt.strftime("%Y%m%d") + "2359"
        
        print(f"\n📅 Processing Month: {start_str[:8]} ~ {end_str[:8]}")
        
        # Pagination Loop
        page = 1
        while True:
            # Standard Service Params
            params = {
                "serviceKey": settings.PUBLIC_DATA_KEY,
                "numOfRows": 999, 
                "pageNo": page,
                "type": "json",
                # Standard Params
                "inqryDiv": "1", # 1: Registration Date, 2: Notice Date, 3: Opening Date
                "inqryBgnDt": start_str,
                "inqryEndDt": end_str,
            }
            
            try:
                response = requests.get(base_url, params=params, timeout=30, verify=False)
                if response.status_code != 200:
                    print(f"   ❌ API Error: {response.status_code}")
                    break
                    
                data = response.json()
                items = data.get("response", {}).get("body", {}).get("items", [])
                
                if not items:
                    print(f"   ✅ Finished month (Page {page-1})")
                    break
                    
                if isinstance(items, dict):
                    items = [items]
                    
                # Schema Probe (First item of first page)
                if page == 1 and total_saved == 0 and len(items) > 0:
                    print(f"   🔍 DEBUG SCHEMA: Keys found -> {list(items[0].keys())}")

                # Save to DB
                new_items_count = 0
                for item in items:
                    # Filter: Only Completed
                    # Note: New API might use different status key. 
                    # If 'opengResultNm' missing, try to detect or skip filter for now to see data.
                    item.get("opengResultNm", item.get("bidNtceSttusNm", ""))
                    
                    # For now, if status is empty, we might let it through or log.
                    # But if we rely on "succsbidderNm", that's the main filter.
                    
                    bid_no = f"{item.get('bidNtceNo')}-{item.get('bidNtceOrd')}"
                    
                    # Check Correctness
                    winner_name = item.get("succsbidderNm", item.get("scsbidderNm", ""))
                    if not winner_name: 
                        # Try to find any winner field
                        continue
                    
                    # Upsert check (Simple exist check to be faster)
                    # For huge data, we might want bulk insert or ignore duplicate errors
                    # But for now, simple check
                    exists = db.query(models.OpeningResult.bid_no).filter_by(bid_no=bid_no).first()
                    if exists:
                        continue
                        
                    try:
                        w_price = float(item.get("succsbidAmt", "0"))
                        w_rate = float(item.get("succsbidRate", "0"))
                    except:
                        w_price = 0
                        w_rate = 0
                        
                    opendt_str = item.get("opengDt", "")
                    try:
                         op_date = datetime.strptime(opendt_str, "%Y%m%d%H%M")
                    except:
                         op_date = datetime.now()

                    res_obj = models.OpeningResult(
                        bid_no=bid_no,
                        organization=item.get("ntceInsttNm", "Unknown"),
                        region=item.get("refNo", ""), # Often used for Region code or infer from org
                        open_date=op_date,
                        winner_company=winner_name,
                        winner_price=w_price,
                        winner_rate=w_rate,
                        crawled_at=datetime.now()
                    )
                    db.add(res_obj)
                    new_items_count += 1
                
                db.commit()
                total_saved += new_items_count
                print(f"   -> Page {page}: Saved {new_items_count} records (Total: {total_saved})")
                
                page += 1
                time.sleep(0.5) # Be polite to API
                
            except Exception as e:
                print(f"   ⚠️ Error on Page {page}: {e}")
                time.sleep(2) # Retry wait
                # allow continue
                
    elapsed = time.time() - start_time
    print("\n🎉 Nationwide Crawl Complete!")
    print(f"⏱️ Time Taken: {elapsed/60:.1f} minutes")
    print(f"📊 Total Records Added: {total_saved}")
    db.close()

if __name__ == "__main__":
    # Default to 1 month for testing, verify logic first
    # Change to 12 for full run
    months_arg = 1 
    if len(sys.argv) > 1:
        months_arg = int(sys.argv[1])
        
    crawl_nationwide_history(months=months_arg)
