import sys
import os
import random
from datetime import datetime, timedelta

# Add backend to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.db.session import SessionLocal, engine
from app.db import models

def generate_mock_data(count: int = 1000):
    """
    Generate realistic mock OpeningResults for testing analytics.
    """
    models.Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    
    agencies = [
        "서울특별시 강남구", "서울특별시청", "경기도청", "부산광역시청", 
        "국토교통부", "한국전력공사", "한국토지주택공사", "인천광역시 교육청"
    ]
    
    companies = [
        "희망건설", "성실전기", "미래산업", "대박개발", "가나다건설", 
        "우리조경", "푸른환경", "제일건축", "태양설비", "한마음공사"
    ]
    
    print(f"🚀 Generating {count} mock opening results...")
    
    for i in range(count):
        # Date: Random in last 1 year
        days_ago = random.randint(1, 365)
        open_date = datetime.now() - timedelta(days=days_ago)
        
        # Agency
        agency = random.choice(agencies)
        
        # Region
        region = agency[:2] # e.g. 서울, 경기
        
        # Basic Price: 50m ~ 1000m
        basic_price = random.randint(50, 1000) * 1000000
        
        # Winner Rate: 
        # Construction lower limit is usually 87.745%.
        # Bids are usually between 87.745% and 88.000%.
        # Let's start with a normal distribution around 87.755
        
        # 10% outliers (Mistakes or high bids)
        if random.random() < 0.1:
            w_rate = random.uniform(86.0, 89.0)
        else:
            # Sweet spot
            w_rate = random.uniform(87.745, 87.800)
            
        w_price = basic_price * (w_rate / 100.0)
        
        bid_no = f"MOCK-{datetime.now().year}-{i:05d}"
        
        obj = models.OpeningResult(
            bid_no=bid_no,
            organization=agency,
            region=region,
            open_date=open_date,
            basic_price=basic_price,
            winner_company=random.choice(companies) + f" {random.randint(1,99)}호",
            winner_price=int(w_price),
            winner_rate=round(w_rate, 5),
            participants_count=random.randint(50, 400),
            crawled_at=datetime.now()
        )
        db.add(obj)
        
        if i % 100 == 0:
            print(f"   -> Generated {i} records...")
            
    db.commit()
    print(f"🎉 Successfully inserted {count} mock records.")
    db.close()

if __name__ == "__main__":
    count_arg = 1000
    if len(sys.argv) > 1:
        count_arg = int(sys.argv[1])
    generate_mock_data(count_arg)
