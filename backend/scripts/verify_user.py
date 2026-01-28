import requests
import json

try:
    resp = requests.get("http://127.0.0.1:8000/api/v1/users/me")
    print(f"Status: {resp.status_code}")
    if resp.status_code == 200:
        print(json.dumps(resp.json(), indent=2, ensure_ascii=False))
    else:
        print(resp.text)
except Exception as e:
    print(f"Error: {e}")
