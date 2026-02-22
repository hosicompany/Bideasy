import json
import sqlite3
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.db.session import get_db
from main import app


@pytest.fixture(scope="session")
def engine():
    engine = create_engine(
        "sqlite:///./test.db",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)
    engine.dispose()
    import os
    if os.path.exists("./test.db"):
        os.remove("./test.db")


@pytest.fixture
def db_session(engine):
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.rollback()
    session.close()


@pytest.fixture
def client(db_session):
    def _override():
        yield db_session

    app.dependency_overrides[get_db] = _override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def historical_test_db(tmp_path):
    """Small SQLite DB mirroring bid_results table for testing
    organization_insights and bid_verifier services."""
    db_file = tmp_path / "test_historical.db"
    conn = sqlite3.connect(str(db_file))
    conn.execute("""
        CREATE TABLE bid_results (
            bid_ntce_no TEXT,
            bid_ntce_nm TEXT,
            dminstt_nm TEXT,
            sucsfbid_amt REAL,
            sucsfbid_rate REAL,
            sucsfbid_corp_nm TEXT,
            bsis_amt REAL,
            bid_type TEXT,
            data_json TEXT
        )
    """)

    now = datetime.now()
    recent = (now - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
    old = (now - timedelta(days=365)).strftime("%Y-%m-%d %H:%M:%S")

    rows = [
        # "서울시청" — 6 recent, 4 old (rates: 87.8~89.1 recent, 86.2~87.0 old)
        ("BID001", "공사A", "서울시청", 88500000, 88.50, "업체A", 100000000,
         "construction", json.dumps({"prtcptCnum": "15", "rlOpengDt": recent})),
        ("BID002", "공사B", "서울시청", 87900000, 87.90, "업체B", 100000000,
         "construction", json.dumps({"prtcptCnum": "20", "rlOpengDt": recent})),
        ("BID003", "공사C", "서울시청", 89100000, 89.10, "업체C", 100000000,
         "construction", json.dumps({"prtcptCnum": "8", "rlOpengDt": recent})),
        ("BID004", "공사D", "서울시청", 88000000, 88.00, "업체D", 100000000,
         "construction", json.dumps({"prtcptCnum": "12", "rlOpengDt": recent})),
        ("BID005", "공사E", "서울시청", 87800000, 87.80, "업체E", 100000000,
         "construction", json.dumps({"prtcptCnum": "5", "rlOpengDt": recent})),
        ("BID006", "공사F", "서울시청", 88200000, 88.20, "업체F", 100000000,
         "construction", json.dumps({"prtcptCnum": "18", "rlOpengDt": recent})),
        ("BID007", "공사G", "서울시청", 86500000, 86.50, "업체G", 100000000,
         "construction", json.dumps({"prtcptCnum": "25", "rlOpengDt": old})),
        ("BID008", "공사H", "서울시청", 87000000, 87.00, "업체H", 100000000,
         "construction", json.dumps({"prtcptCnum": "30", "rlOpengDt": old})),
        ("BID009", "공사I", "서울시청", 86200000, 86.20, "업체I", 100000000,
         "construction", json.dumps({"prtcptCnum": "10", "rlOpengDt": old})),
        ("BID010", "공사J", "서울시청", 86800000, 86.80, "업체J", 100000000,
         "construction", json.dumps({"prtcptCnum": "22", "rlOpengDt": old})),
        # "강남구청" — 2 goods records
        ("BID011", "물품A", "강남구청", 89500000, 89.50, "업체K", 100000000,
         "goods", json.dumps({"prtcptCnum": "7", "rlOpengDt": recent})),
        ("BID012", "물품B", "강남구청", 88000000, 88.00, "업체L", 100000000,
         "goods", json.dumps({"prtcptCnum": "3", "rlOpengDt": old})),
        # "부산광역시" — 1 record (for global avg calculation)
        ("BID013", "공사M", "부산광역시", 87500000, 87.50, "업체M", 100000000,
         "construction", json.dumps({"prtcptCnum": "40", "rlOpengDt": old})),
        # Filtered out: rate=45 (below 50 threshold)
        ("BID014", "공사N", "서울시청", 45000000, 45.00, "업체N", 100000000,
         "construction", json.dumps({"prtcptCnum": "2", "rlOpengDt": recent})),
    ]
    conn.executemany(
        "INSERT INTO bid_results VALUES (?,?,?,?,?,?,?,?,?)", rows
    )
    conn.commit()
    conn.close()
    return db_file
