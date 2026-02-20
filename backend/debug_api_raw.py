import requests

# Mock Settings if needed, or import
from app.core.config import settings
# Manually load env if needed or assume settings works if run from right place

def test_raw():
    url = "http://apis.data.go.kr/1230000/BidPublicInfoService04/getBidPblancListInfoCnstwk"
    
    # Use yesterday
    from datetime import datetime, timedelta
    yesterday = datetime.now() - timedelta(days=1)
    
    start_str = yesterday.strftime("%Y%m%d") + "0000"
    end_str = yesterday.strftime("%Y%m%d") + "2359"
    
    params = {
        "serviceKey": settings.PUBLIC_DATA_KEY, # Raw Key
        "numOfRows": 10,
        "pageNo": 1,
        "inqryDiv": 1,
        "bidNtceDtBgn": start_str[:8], # Notice API uses different param names sometimes?
        "bidNtceDtEnd": end_str[:8],
        "type": "json"
    }
    
    # Notice API params: inqryDiv(1), bidNtceDtBgn(YYYYMMDD), bidNtceDtEnd
    # Let's double check params. Usually opengBgnDt is for Opening.
    # For Notice List: 'inqryDiv', 'inqryBgnDt', 'inqryEndDt' ...
    # API docs say: inqryDiv=1 -> use 'inqryBgnDt' and 'inqryEndDt'.
    
    params = {
        "serviceKey": settings.PUBLIC_DATA_KEY,
        "numOfRows": 10,
        "pageNo": 1,
        "inqryDiv": 1,
        "inqryBgnDt": start_str[:10], # YYYYMMDDHH is often required or just YYYYMMDD
        "inqryEndDt": end_str[:10],
        "type": "json"
    }
    
    # Actually, let's use standard YYYYMMDD0000 format often accepted
    params["inqryBgnDt"] = start_str
    params["inqryEndDt"] = end_str
    
    print(f"Requesting: {url}")
    print(f"Params: {params}")
    
    try:
        res = requests.get(url, params=params, verify=False, timeout=10)
        print(f"Status: {res.status_code}")
        print(f"Body: {res.text[:1000]}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_raw()
