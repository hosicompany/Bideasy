"""
HTTPS로 테스트
"""
import requests
from datetime import datetime, timedelta

API_KEY = '22a4656cd4236b19403593956cd24357d9a27f5c3d3dcdb4b7c19fcc7a1c80a4'
BASE_URL = 'https://apis.data.go.kr/1230000/as/ScsbidInfoService'

operations = [
    'getScsbidListSttusThng',
    'getScsbidListSttusCnstwk', 
    'getOpengResultListInfoCnstwk',
]

end_dt = datetime.now().strftime('%Y%m%d')
start_dt = (datetime.now() - timedelta(days=30)).strftime('%Y%m%d')

for op in operations:
    url = f'{BASE_URL}/{op}'
    params = {
        'serviceKey': API_KEY,
        'type': 'json',
        'numOfRows': 3,
        'pageNo': 1,
        'inqryBgnDt': start_dt,
        'inqryEndDt': end_dt,
    }
    
    print(f'Testing: {op}')
    print(f'URL: {url}')
    
    r = requests.get(url, params=params, timeout=15)
    print(f'Status: {r.status_code}')
    
    if r.status_code == 200:
        try:
            data = r.json()
            header = data.get('response', {}).get('header', {})
            code = header.get('resultCode')
            msg = header.get('resultMsg', '')
            print(f'Result: {code} - {msg}')
            
            body = data.get('response', {}).get('body', {})
            total = body.get('totalCount', 0)
            print(f'Total: {total}')
            
            if code == '00' and total > 0:
                print('SUCCESS!')
        except Exception as e:
            print(f'Parse Error: {e}')
            print(f'Response: {r.text[:300]}')
    else:
        print(f'Error: {r.text[:200]}')
    
    print()
