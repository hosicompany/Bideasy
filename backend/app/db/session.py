from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.core.config import settings

# Construct Database URL
# For easier local setup without Docker, we will use SQLite by default.
SQLALCHEMY_DATABASE_URL = "sqlite:///./bideasy.db"

# connect_args={"check_same_thread": False} is required for SQLite
engine = create_engine(
    SQLALCHEMY_DATABASE_URL, 
    connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
