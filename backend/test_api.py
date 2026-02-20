import httpx

url = 'https://apis.data.go.kr/1230000/as/ScsbidInfoService/getScsbidListSttusThng'
params = {
    'serviceKey': 'fa268326385baba6b21a78ceb898d00b382b4ac3cf1d610e3c647ef3422e5905',
    'pageNo': '1',
    'numOfRows': '3',
    'inqryDiv': '1',
    'type': 'json',
    'inqryBgnDt': '202401010000',
    'inqryEndDt': '202401312359'
}

r = httpx.get(url, params=params, timeout=30)
print(f'Status: {r.status_code}')
data = r.json()
print(f"Total: {data['response']['body']['totalCount']}건")
print(f"Items: {len(data['response']['body']['items'])}개")
