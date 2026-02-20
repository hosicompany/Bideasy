import requests
import sys
import os
from urllib.parse import unquote
from datetime import datetime, timedelta

# Add backend to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from app.core.config import settings

def test_date_format():
    key = unquote(settings.PUBLIC_DATA_KEY)
    url = "http://apis.data.go.kr/1230000/BidPublicInfoService04/getBidPblancListInfoCnstwk"
    
    # Try 8 digit date
    end_dt = datetime.now()
    start_dt = end_dt - timedelta(days=5)
    
    # 8 Digits
    s_date = start_dt.strftime("%Y%m%d")
    e_date = end_dt.strftime("%Y%m%d")
    
    
    # Manual URL
    query = f"serviceKey={key}&numOfRows=1&pageNo=1&inqryDiv=1&inqryBgnDt={s_date}&inqryEndDt={e_date}&type=json"
    final_url = f"{url}?{query}"
    
    print(f"Testing 8-digit Date: {final_url}")
    
    try:
        res = requests.get(final_url, verify=False, timeout=5)
        print(f"Status: {res.status_code}")
        print(f"Body: {res.text[:300]}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_date_format()
