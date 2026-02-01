from fastapi import FastAPI
# Force reload trigger
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.api.v1.api import api_router
from app.db.base import Base
from app.db.session import engine

# Create Tables (Simple migration for dev)
Base.metadata.create_all(bind=engine)

# Auto-migration for new fields (Dev mode)
from sqlalchemy import text
with engine.connect() as conn:
    try:
        conn.execute(text("SELECT a_value FROM notices LIMIT 1"))
    except Exception:
        print("Migrating DB: Adding a_value and net_cost columns...")
        try:
            conn.execute(text("ALTER TABLE notices ADD COLUMN a_value INTEGER DEFAULT 0"))
            conn.execute(text("ALTER TABLE notices ADD COLUMN net_cost INTEGER DEFAULT 0"))
            conn.commit()
        except Exception as e:
            print(f"Migration failed: {e}")

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.PROJECT_VERSION,
    description="BidEasy Backend API"
)

# Set all CORS enabled origins
origins = [
    "http://localhost",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:8080",
    "*" 
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix=settings.API_V1_STR)

@app.get("/")
async def root():
    return {"message": f"Welcome to {settings.PROJECT_NAME} API"}

