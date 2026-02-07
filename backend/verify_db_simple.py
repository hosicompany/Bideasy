import sys
import os
from datetime import datetime

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.db.session import engine, SessionLocal
from app.db import models

def check():
    print("1. DB Init")
    try:
        models.Base.metadata.create_all(bind=engine)
        print("   -> Init OK")
    except Exception as e:
        print(f"   -> Init Failed: {e}")
        return

    print("2. Save Test")
    try:
        db = SessionLocal()
        # Create dummy
        dummy = models.OpeningResult(
            bid_no="TEST-001",
            organization="TestOrg",
            winner_company="TestComp",
            winner_price=100.0,
            winner_rate=88.8,
            open_date=datetime.now(),
            participants_count=10
        )
        db.merge(dummy) # upsert
        db.commit()
        print("   -> Save OK")
        
        count = db.query(models.OpeningResult).count()
        print(f"   -> Count: {count}")
        db.close()
    except Exception as e:
        print(f"   -> Save Failed: {e}")

if __name__ == "__main__":
    check()
