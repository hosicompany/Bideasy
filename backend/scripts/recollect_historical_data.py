import os
import requests
import json
import sqlite3
from datetime import datetime, timedelta
import time

# --- Configuration ---
PUBLIC_DATA_KEY = os.environ.get("PUBLIC_DATA_KEY") or ""
if not PUBLIC_DATA_KEY:
    raise SystemExit(
        "PUBLIC_DATA_KEY 환경 변수가 없습니다. "
        "backend/.env 에 설정하거나 export PUBLIC_DATA_KEY=... 후 재실행하세요."
    )
DB_PATH = "historical_results_v2.db"
PROGRESS_PATH = "collection_progress.json"

# API Endpoint: 개찰결과정보서비스
BASE_URL = "https://apis.data.go.kr/1230000/ao/PubDataOpnStdService/getDataSetOpnStdScsbidInfo"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS historical_results (
            bid_no TEXT PRIMARY KEY,
            title TEXT,
            organization TEXT,
            open_date TEXT,
            basic_price REAL,
            reserved_price REAL,
            bid_method TEXT,
            winner_company TEXT,
            winner_price REAL,
            winner_rate REAL,
            participants_count INTEGER,
            collected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    return conn

def update_progress(current_count, target_count, current_date, start_time):
    elapsed = time.time() - start_time
    progress = {
        "current_count": current_count,
        "target_count": target_count,
        "percent": round((current_count / target_count * 100), 2) if target_count > 0 else 0,
        "current_date": current_date,
        "elapsed_seconds": round(elapsed),
        "status": "running",
        "last_update": datetime.now().isoformat()
    }
    with open(PROGRESS_PATH, "w") as f:
        json.dump(progress, f)

def fetch_batch(page=1, size=100, start_date=None, end_date=None):
    params = {
        "serviceKey": PUBLIC_DATA_KEY,
        "numOfRows": size,
        "pageNo": page,
        "inqryDiv": 1,
        "opengBgnDt": start_date,
        "opengEndDt": end_date,
        "type": "json"
    }
    try:
        response = requests.get(BASE_URL, params=params, timeout=20)
        if response.status_code != 200:
            return []
        data = response.json()
        items = data.get("response", {}).get("body", {}).get("items", [])
        if not items: return []
        if isinstance(items, dict): items = [items]
        return items
    except:
        return []

def process_and_save(conn, items):
    cursor = conn.cursor()
    saved = 0
    for item in items:
        bid_no = f"{item.get('bidNtceNo')}-{item.get('bidNtceOrd')}"
        try:
            row = (
                bid_no,
                item.get("bidNtceNm"),
                item.get("ntceInsttNm"),
                item.get("opengDt"),
                float(item.get("bsisAmt", 0) or 0),
                float(item.get("prearPrce", 0) or 0),
                item.get("bidMthdNm"),
                item.get("succsbidderNm"),
                float(item.get("succsbidAmt", 0) or 0),
                float(item.get("succsbidRate", 0) or 0),
                int(item.get("prtcptCnum", 0) or 0)
            )
            cursor.execute("INSERT OR REPLACE INTO historical_results VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)", row)
            saved += 1
        except: continue
    conn.commit()
    return saved

def run_collection(years=5):
    conn = init_db()
    total_saved = 0
    target_months = int(years * 12)
    start_time = time.time()
    
    end_date_obj = datetime.now()
    
    for i in range(target_months):
        month_end = end_date_obj - timedelta(days=i*30)
        month_start = month_end - timedelta(days=30)
        start_str = month_start.strftime("%Y%m%d") + "0000"
        end_str = month_end.strftime("%Y%m%d") + "2359"
        
        page = 1
        while True:
            items = fetch_batch(page=page, size=100, start_date=start_str, end_date=end_str)
            if not items: break
            
            count = process_and_save(conn, items)
            total_saved += count
            
            # Estimating total (Roughly 25k per month based on 1.38M/60 months)
            update_progress(total_saved, target_months * 23000, month_start.strftime("%Y-%m"), start_time)
            
            if len(items) < 100: break
            page += 1
            time.sleep(0.3)

    update_progress(total_saved, total_saved, "Complete", start_time)
    with open(PROGRESS_PATH, "r") as f:
        data = json.load(f)
        data["status"] = "completed"
    with open(PROGRESS_PATH, "w") as f:
        json.dump(data, f)
    conn.close()

if __name__ == "__main__":
    run_collection(years=5)
