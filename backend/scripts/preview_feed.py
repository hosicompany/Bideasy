
import sys
import os
import locale

# Force UTF-8 for Windows console
sys.stdout.reconfigure(encoding='utf-8')

# Add backend directory to path so we can import app modules
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from app.db.session import SessionLocal
from app.db.models import Notice

def preview_feed():
    db = SessionLocal()
    notices = db.query(Notice).order_by(Notice.start_date.desc()).limit(10).all()
    
    print("\n" + "="*50)
    print("📱 [Simulation] BidEasy App Feed Preview")
    print("="*50)
    
    if not notices:
        print("No notices found.")
        return

    for i, notice in enumerate(notices, 1):
        # Format price
        price_str = f"{int(notice.basic_price):,}"
        title = notice.title
        if len(title) > 30:
            title = title[:27] + "..."
            
        print(f"{i}. [{notice.bid_no}] {title}")
        print(f"   💰 Basic Price: {price_str} KRW")
        print(f"   📅 End Date: {notice.end_date.strftime('%Y-%m-%d %H:%M')}")
        print("-" * 50)
        
    print(f"\n✅ Total {len(notices)} real notices ready to be displayed in the App.")
    db.close()

if __name__ == "__main__":
    preview_feed()
