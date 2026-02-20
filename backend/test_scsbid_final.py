"""
ScsbidInfoService API 테스트 - 문서 기반 정확한 엔드포인트
"""
import requests
from datetime import datetime, timedelta

API_KEY = '22a4656cd4236b19403593956cd24357d9a27f5c3d3dcdb4b7c19fcc7a1c80a4'
BASE_URL = 'http://apis.data.go.kr/1230000/as/ScsbidInfoService'

# 문서에서 확인한 정확한 오퍼레이션
OPERATIONS = [
    'getScsbidListSttusThng',      # 낙찰자 결정 현황 물품
    'getScsbidListSttusCnstwk',    # 낙찰자 결정 현황 공사
    'getScsbidListSttusServc',     # 낙찰자 결정 현황 용역
    'getOpengResultListInfoThng',  # 개찰결과 물품
    'getOpengResultListInfoCnstwk', # 개찰결과 공사
    'getOpengResultListInfoOpengCompt', # 개찰완료
]

def test_operation(op_name):
    url = f'{BASE_URL}/{op_name}'
    
    end_dt = datetime.now().strftime('%Y%m%d')
    start_dt = (datetime.now() - timedelta(days=30)).strftime('%Y%m%d')
    
    params = {
        'serviceKey': API_KEY,
        'type': 'json',
        'numOfRows': 3,
        'pageNo': 1,
        'inqryBgnDt': start_dt,
        'inqryEndDt': end_dt,
    }
    
    print(f'\n{"="*50}')
    print(f'Operation: {op_name}')
    
    try:
        r = requests.get(url, params=params, timeout=15)
        print(f'Status: {r.status_code}')
        
        if r.status_code == 200:
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
                
                if items:
                    print(f'Found {len(items)} items!')
                    # Show sample data
                    item = items[0]
                    print('Sample fields:')
                    for key in list(item.keys())[:8]:
                        print(f'  {key}: {str(item.get(key, ""))[:40]}')
                    return True
        else:
            print(f'Error: {r.text[:150]}')
    except Exception as e:
        print(f'Exception: {e}')
    
    return False

if __name__ == '__main__':
    print('Testing ScsbidInfoService API')
    print(f'Base: {BASE_URL}')
    
    success = []
    for op in OPERATIONS:
        if test_operation(op):
            success.append(op)
            print('>>> SUCCESS!')
    
    print(f'\n{"="*50}')
    print(f'Working Operations: {len(success)}/{len(OPERATIONS)}')
    for s in success:
        print(f'  - {s}')
