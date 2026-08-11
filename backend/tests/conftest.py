import json
import sqlite3
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core import cache as _cache
from app.core.config import settings as _settings
from app.db.base import Base
from app.db.session import get_db
from main import app

# 테스트에서는 레이트리밋 비활성화 — 누적 호출이 분당 한도에 걸려 flaky 해지는 것 방지.
# (레이트리밋 동작은 test_rate_limit.py 에서 별도로 명시 검증)
from app.core.rate_limit import limiter as _limiter
_limiter.enabled = False

# ── Redis 격리 ──────────────────────────────────────────────────────────────
# 테스트는 로컬에 떠 있는 Redis 를 **말없이** 잡아 쓴다(`_get_redis()` 는 연결되면
# 그냥 쓴다). 그러면 두 가지가 깨진다:
#   ① 개발자의 dev Redis(db 0)를 테스트가 오염시킨다.
#   ② 카운터가 실행 간에 살아남아 두 번째 전체 실행부터 실패한다 — 일일/시간당
#      카운터(`bideasy:ai_limit:{user_id}:{날짜}`·`bideasy:lead_rl:capture:{ip}`)는
#      TTL 이 24시간·1시간이라 다음 실행까지 남는데, DB 는 매 실행 새로 만들어져
#      user id 가 1부터 다시 매겨진다. 즉 앞 실행에서 한도를 소진한 카운터를 다음
#      실행의 **다른 사용자**가 물려받아 429 를 받는다.
# 그래서 전용 DB 인덱스로 갈라 두고, 세션 시작 때 우리 네임스페이스만 비운다.
# Redis 가 없으면(`_get_redis()` → None) 각 호출부의 in-memory 폴백이 도는데 그건
# 프로세스마다 초기화되므로 이미 격리돼 있다 — 아래 훅도 조용히 no-op 이 된다.
TEST_REDIS_DB = 15
_settings.REDIS_DB = TEST_REDIS_DB
_cache._redis_client = None  # 이미 dev DB 로 연결됐을 수 있으니 싱글턴 리셋


@pytest.fixture(scope="session", autouse=True)
def _isolate_redis():
    """세션 시작·종료 시 테스트 DB 의 `bideasy:*` 키를 비운다.

    FLUSHDB 대신 접두사 스캔인 이유: 전용 인덱스라도 남의 데이터를 지울 권한은 없다.
    """
    def _purge():
        r = _cache._get_redis()
        if r is None:
            return
        try:
            keys = list(r.scan_iter(match="bideasy:*", count=500))
            if keys:
                r.delete(*keys)
        except Exception:
            pass  # Redis 정리 실패가 테스트를 깨뜨리지는 않는다

    _purge()
    yield
    _purge()


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
def pro_client(db_session):
    """TestClient with a Pro-tier user already authenticated."""
    from app.db import models
    from app.core.security import create_access_token

    user = db_session.query(models.User).filter(models.User.email == "test-pro@test.com").first()
    if not user:
        user = models.User(email="test-pro@test.com", hashed_password="x", tier="pro")
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)

    token = create_access_token({"sub": str(user.id)})

    def _override():
        yield db_session

    app.dependency_overrides[get_db] = _override
    with TestClient(app) as c:
        c.headers["Authorization"] = f"Bearer {token}"
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


@pytest.fixture
def pro_plus_client(db_session):
    """TestClient with a Pro+ tier user already authenticated."""
    from app.db import models
    from app.core.security import create_access_token

    user = db_session.query(models.User).filter(models.User.email == "test-proplus@test.com").first()
    if not user:
        user = models.User(email="test-proplus@test.com", hashed_password="x", tier="pro_plus")
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)

    token = create_access_token({"sub": str(user.id)})

    def _override():
        yield db_session

    app.dependency_overrides[get_db] = _override
    with TestClient(app) as c:
        c.headers["Authorization"] = f"Bearer {token}"
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def free_client(db_session):
    """TestClient with a Free tier user already authenticated."""
    from app.db import models
    from app.core.security import create_access_token

    user = db_session.query(models.User).filter(models.User.email == "test-free@test.com").first()
    if not user:
        user = models.User(
            email="test-free@test.com", hashed_password="x", tier="free", points=3000,
        )
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)

    token = create_access_token({"sub": str(user.id)})

    def _override():
        yield db_session

    app.dependency_overrides[get_db] = _override
    with TestClient(app) as c:
        c.headers["Authorization"] = f"Bearer {token}"
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def admin_client(db_session):
    """TestClient with an admin user (is_admin=True) already authenticated."""
    from app.db import models
    from app.core.security import create_access_token

    user = db_session.query(models.User).filter(models.User.email == "test-admin@test.com").first()
    if not user:
        user = models.User(
            email="test-admin@test.com",
            hashed_password="x",
            tier="free",
            is_admin=True,
        )
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)

    token = create_access_token({"sub": str(user.id)})

    def _override():
        yield db_session

    app.dependency_overrides[get_db] = _override
    with TestClient(app) as c:
        c.headers["Authorization"] = f"Bearer {token}"
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def sample_notice(db_session):
    """Insert a sample Notice into the test DB and return it."""
    from app.db import models

    notice = db_session.query(models.Notice).filter(models.Notice.bid_no == "TEST-001").first()
    if not notice:
        notice = models.Notice(
            bid_no="TEST-001",
            title="서울시 강남구 구민회관 리모델링 공사",
            basic_price=500000000,
            contract_type="CONSTRUCTION",
            organization="강남구청",
            start_date=datetime.now(),
            end_date=datetime.now() + timedelta(days=7),
        )
        db_session.add(notice)
        db_session.commit()
        db_session.refresh(notice)
    return notice
