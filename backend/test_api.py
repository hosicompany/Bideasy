
import requests
from datetime import datetime, timedelta
import os

# User provided key
KEY = "22a4656cd4236b19403593956cd24357d9a27f5c3d3dcdb4b7c19fcc7a1c80a4"
URL = "https://apis.data.go.kr/1230000/BidPublicInfoService04/getBidPblancListInfoCnstwk"

def test_api():
    end_date_str = datetime.now().strftime("%Y%m%d") + "2359"
    start_date_str = (datetime.now() - timedelta(days=5)).strftime("%Y%m%d") + "0000"

    params = {
        "serviceKey": KEY,
        "numOfRows": 2,
        "pageNo": 1,
        "inqryDiv": 1,
        "inqryBgnDt": start_date_str,
        "inqryEndDt": end_date_str,
        "type": "json"
    }

    print(f"Testing URL: {URL}")
    print(f"Params: {params}")

    try:
        # data.go.kr keys often need to be sent EXACTLY as provided without further encoding if they are already decoded.
        # But requests will URL-encode params. 
        # If the key provided by user is ALREADY encoded (has %), we should unquote it for requests params?
        # The user's key has NO %. It looks like Hex.
        
        response = requests.get(URL, params=params)
        
        print(f"Final Requested URL: {response.url}")
        print(f"Status Code: {response.status_code}")
        print(f"Raw Response Body:\n{response.text}") # Print full body to see XML error
        
        response.encoding = 'utf-8' # Ensure utf-8
        print(f"Decoded Response Body:\n{response.text}")
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_api()
