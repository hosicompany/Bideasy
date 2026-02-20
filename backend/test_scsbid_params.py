"""
ScsbidInfoService 파라미터 테스트
"""
import requests
from datetime import datetime, timedelta

API_KEY = '22a4656cd4236b19403593956cd24357d9a27f5c3d3dcdb4b7c19fcc7a1c80a4'
BASE = 'https://apis.data.go.kr/1230000/ScsbidInfoService'

end_dt = datetime.now().strftime('%Y%m%d')
start_dt = (datetime.now() - timedelta(days=30)).strftime('%Y%m%d')

endpoints = ['getScsbidListCnstwk', 'getScsbidListThng', 'getScsbidListServc']

for ep in endpoints:
    url = f'{BASE}/{ep}'
    print(f'\n{"="*50}')
    print(f'Testing: {ep}')
    print(f'URL: {url}')
    
    # 여러 파라미터 조합
    params = {
        'serviceKey': API_KEY, 
        'type': 'json', 
        'numOfRows': 3, 
        'pageNo': 1, 
        'inqryBgnDt': start_dt, 
        'inqryEndDt': end_dt
    }
    
    r = requests.get(url, params=params, timeout=15)
    print(f'Status: {r.status_code}')
    
    if r.status_code == 200:
        try:
            data = r.json()
            header = data.get('response', {}).get('header', {})
            code = header.get('resultCode')
            msg = header.get('resultMsg')
            print(f'Result: {code} - {msg}')
            
            if code == '00':
                body = data.get('response', {}).get('body', {})
                total = body.get('totalCount', 0)
                print(f'Total: {total}')
                
                items = body.get('items', [])
                if isinstance(items, dict):
                    items = [items]
                
                if items:
                    print(f'Sample Keys: {list(items[0].keys())[:8]}')
                    print('SUCCESS!')
        except Exception as e:
            print(f'Parse Error: {e}')
            print(f'Response: {r.text[:300]}')
    else:
        print(f'Error Response: {r.text[:200]}')
