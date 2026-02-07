import requests
from app.core.config import settings

def test_detail_api(bid_no):
    url = "https://apis.data.go.kr/1230000/PubDataOpnStdService/getDataSetOpnStdBidPblancInfo"
    params = {
        "serviceKey": settings.PUBLIC_DATA_KEY,
        "numOfRows": 1,
        "pageNo": 1,
        "type": "json",
        "bidNtceNo": bid_no,
    }
    print(f"Testing Detail API for {bid_no}")
    try:
        resp = requests.get(url, params=params)
        print("Status:", resp.status_code)
        print("Raw Content:", resp.text[:500])
        
        data = resp.json()
        item = data['response']['body']['items'][0]
        print("Keys:", item.keys())
        if 'ntceSpecDocUrl1' in item:
            print("Found URL:", item['ntceSpecDocUrl1'])
        else:
            print("No ntceSpecDocUrl1 found")
            
    except Exception as e:
        print("Error:", e)

if __name__ == "__main__":
    test_detail_api("R25BK01253548")
