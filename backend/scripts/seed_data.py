
import sys
import os
from datetime import datetime, timedelta

# Add backend directory to path so we can import app modules
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from app.db.session import SessionLocal, engine
from app.db.base import Base
from app.db.models import Notice

def seed_data():
    # Ensure tables exist
    Base.metadata.create_all(bind=engine)
    
    db = SessionLocal()
    
    # Check if data exists
    if db.query(Notice).first():
        print("Data already exists. Skipping seed.")
        db.close()
        return

    print("Seeding data...")
    notices = [
        Notice(
            bid_no="20240121001",
            title="[Hosi Company] 강남구 구민회관 리모델링 공사",
            content="강남구 구민회관 리모델링 공사 건입니다.",
            basic_price=500000000.0,
            start_date=datetime.now(),
            end_date=datetime.now() + timedelta(days=7)
        ),
        Notice(
            bid_no="20240121002",
            title="서초구 도로 포장 공사",
            content="서초구 관내 도로 포장 공사입니다.",
            basic_price=120000000.0,
            start_date=datetime.now(),
            end_date=datetime.now() + timedelta(days=5)
        ),
        Notice(
            bid_no="20240121003",
            title="분당 판교 도서관 신축 전기 공사",
            content="판교 도서관 신축 전기 공사 입찰 공고",
            basic_price=350000000.0,
            start_date=datetime.now(),
            end_date=datetime.now() + timedelta(days=10)
        ),
        Notice(
            bid_no="20240121004",
            title="송파구 체육센터 소방 시설 보수",
            content="소방 시설 보수 공사",
            basic_price=85000000.0,
            start_date=datetime.now(),
            end_date=datetime.now() + timedelta(days=3)
        ),
    ]

    for notice in notices:
        db.add(notice)
    
    db.commit()
    print("Seeding completed successfully!")
    db.close()

if __name__ == "__main__":
    seed_data()
