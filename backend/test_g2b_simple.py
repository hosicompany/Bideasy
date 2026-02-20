"""
조달청 API 간단 테스트
"""
import asyncio
import httpx

API_KEY = '22a4656cd4236b19403593956cd24357d9a27f5c3d3dcdb4b7c19fcc7a1c80a4'
BASE_URL = 'http://apis.data.go.kr/1230000'

async def test():
    async with httpx.AsyncClient(timeout=30.0) as client:
        # 물품 낙찰정보 조회
        url = BASE_URL + '/BidResultInfoService/getBidResultListInfoThngPPSSrch'
        params = {
            'serviceKey': API_KEY,
            'type': 'json',
            'numOfRows': 5,
            'pageNo': 1,
        }
        
        print('Calling G2B API...')
        print('URL:', url)
        
        response = await client.get(url, params=params)
        print('Status:', response.status_code)
        
        if response.status_code == 200:
            data = response.json()
            
            if 'response' in data:
                header = data['response'].get('header', {})
                result_code = header.get('resultCode')
                result_msg = header.get('resultMsg')
                print('Result Code:', result_code)
                print('Result Msg:', result_msg)
                
                body = data['response'].get('body', {})
                total = body.get('totalCount', 0)
                print('Total Count:', total)
                
                items = body.get('items', {})
                if isinstance(items, dict):
                    items = items.get('item', [])
                
                if items and len(items) > 0:
                    print('\n=== Sample Data ===')
                    for i, item in enumerate(items[:3]):
                        name = item.get('bidNtceNm', 'N/A')
                        bid_no = item.get('bidNtceNo', 'N/A')
                        amount = item.get('sucsfbidAmt', 'N/A')
                        print(f'\n[{i+1}] {name[:40]}...')
                        print(f'    No: {bid_no}')
                        print(f'    Amount: {amount}')
                    print('\nSUCCESS!')
                else:
                    print('No items found')
            else:
                print('Unexpected response:', str(data)[:300])
        else:
            print('Error:', response.text[:300])

if __name__ == '__main__':
    asyncio.run(test())
