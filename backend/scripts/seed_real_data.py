
import sys
import os
from datetime import datetime, timedelta

# Add backend directory to path so we can import app modules
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from app.db.session import SessionLocal, engine
from app.db.base import Base
from app.services.crawler import CrawlerService

def seed_real_data():
    # Ensure tables exist
    Base.metadata.create_all(bind=engine)
    
    db = SessionLocal()
    
    print("Fetching Real Data from Public Data Portal...")
    try:
        # Fetch 10 items
        notices = CrawlerService.fetch_notices(size=10)
        
        if not notices:
            print("No notices fetched. Check API Key or Service Status.")
            return

        print(f"Fetched {len(notices)} items. Saving to database...")
        saved_count = CrawlerService.save_notices(db, notices)
        print(f"Successfully saved {saved_count} new notices to database.")
        
    except Exception as e:
        print(f"Error seeding data: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    seed_real_data()
