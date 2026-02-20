"""
PPSSrch 접미사 추가하여 테스트
"""
import requests
from datetime import datetime, timedelta

API_KEY = '22a4656cd4236b19403593956cd24357d9a27f5c3d3dcdb4b7c19fcc7a1c80a4'
BASE_URL = 'http://apis.data.go.kr/1230000/as/ScsbidInfoService'

# PPSSrch 접미사가 붙은 오퍼레이션
operations = [
    'getScsbidListSttusThngPPSSrch',      # 낙찰자 결정 현황 물품
    'getScsbidListSttusCnstwkPPSSrch',    # 낙찰자 결정 현황 공사
    'getOpengResultListInfoCnstwkPPSSrch', # 개찰결과 공사
]

# 날짜 형식: YYYYMMDDHHMM
end_dt = datetime.now().strftime('%Y%m%d') + '2359'
start_dt = (datetime.now() - timedelta(days=30)).strftime('%Y%m%d') + '0000'

for op in operations:
    url = f'{BASE_URL}/{op}'
    params = {
        'serviceKey': API_KEY,
        'type': 'json',
        'numOfRows': 5,
        'pageNo': 1,
        'inqryDiv': '1',  # 1=낙찰일시
        'inqryBgnDt': start_dt,
        'inqryEndDt': end_dt,
    }
    
    print(f'\n{"="*50}')
    print(f'Operation: {op}')
    print(f'Date: {start_dt} ~ {end_dt}')
    
    r = requests.get(url, params=params, timeout=15)
    print(f'Status: {r.status_code}')
    
    if r.status_code == 200:
        try:
            data = r.json()
            header = data.get('response', {}).get('header', {})
            code = header.get('resultCode')
            msg = header.get('resultMsg', '')
            print(f'Result: {code} - {msg}')
            
            if code == '00':
                body = data.get('response', {}).get('body', {})
                total = body.get('totalCount', 0)
                print(f'Total: {total}')
                
                items = body.get('items', [])
                if isinstance(items, dict):
                    items = items.get('item', [])
                    if not isinstance(items, list):
                        items = [items]
                
                if items and len(items) > 0:
                    print(f'Found {len(items)} items!')
                    item = items[0]
                    print('Sample:')
                    for key in ['bidNtceNo', 'bidNtceNm', 'sucsfbidAmt', 'opengDt']:
                        if key in item:
                            val = str(item.get(key, ''))[:50]
                            print(f'  {key}: {val}')
                    print('SUCCESS!')
        except Exception as e:
            print(f'Error: {e}')
            print(f'Response: {r.text[:200]}')
    else:
        print(f'Error: {r.text[:100]}')
