import sys
import os

# Add backend to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.db.session import SessionLocal
from app.db import models

def check():
    try:
        db = SessionLocal()
        count = db.query(models.OpeningResult).count()
        print(f"COUNT: {count}")
    except Exception as e:
        print(f"ERROR: {e}")

if __name__ == "__main__":
    check()
