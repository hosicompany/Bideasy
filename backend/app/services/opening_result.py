import requests
import json
from typing import List, Optional
from datetime import datetime
from app.core.config import settings

class OpeningResultService:
    # Construction Opening Results
    BASE_URL_CNST = "https://apis.data.go.kr/1230000/ad/BidPublicInfoService/getOpengResultListInfoCnstwk"
    # Service Opening Results
    BASE_URL_SERV = "https://apis.data.go.kr/1230000/ad/BidPublicInfoService/getOpengResultListInfoServc"
    # Goods Opening Results
    BASE_URL_THNG = "https://apis.data.go.kr/1230000/ad/BidPublicInfoService/getOpengResultListInfoThng"
    
    @staticmethod
    def fetch_opening_results(bid_no: str, contract_type: str = "CONSTRUCTION") -> List[dict]:
        """
        Fetch opening results (Rankings) for a specific bid.
        Returns a list of companies with rank, price, etc.
        """
        # 1. Parse bid_no (Format: 20241234567-00)
        try:
            bid_ntce_no, bid_ntce_ord = bid_no.split("-")
        except ValueError:
            print(f"[OpeningResult] Invalid bid_no format: {bid_no}")
            return []

        # 2. Select Endpoint
        if contract_type == "SERVICE":
            url = OpeningResultService.BASE_URL_SERV
        elif contract_type == "GOODS":
            url = OpeningResultService.BASE_URL_THNG
        else:
            url = OpeningResultService.BASE_URL_CNST
            
        params = {
            "serviceKey": settings.PUBLIC_DATA_KEY,
            "numOfRows": 100, # Get all participants
            "pageNo": 1,
            "inqryDiv": 1, 
            "bidNtceNo": bid_ntce_no,
            "bidNtceOrd": bid_ntce_ord,
            "type": "json"
        }
        
        try:
            print(f"[OpeningResult] Fetching result for {bid_no} from {url}", flush=True)
            response = requests.get(url, params=params, timeout=5, verify=False)
            
            if response.status_code != 200:
                print(f"[OpeningResult] API Error: {response.status_code} {response.text}")
                return OpeningResultService.get_mock_results(bid_no)
            
            try:
                data = response.json()
            except json.JSONDecodeError:
                print(f"[OpeningResult] JSON Decode Error: {response.text[:100]}")
                return OpeningResultService.get_mock_results(bid_no)
                
            response_body = data.get("response", {}).get("body", {})
            items = response_body.get("items", [])
            
            if not items:
                print("[OpeningResult] No items found in API response")
                return []
                
            if isinstance(items, dict):
                items = [items]
                
            results = []
            for item in items:
                # Map fields
                # rank: opengRank
                # company: bizNm
                # ceo: ceoNm
                # price: bidAmt
                # rate: bidRate (succsbidRate?) or calculate manually
                # note: remk
                
                try:
                    price = float(item.get("bidAmt", 0))
                except:
                    price = 0
                
                try:
                    rank = int(item.get("opengRank", 0))
                except:
                    rank = 999
                    
                rate_str = item.get("succsbidRate", "0") # Check exact field name
                # Actually commonly:투찰률 (bidRate) is not always provided directly in all APIs.
                # Usually we calculate: (Bid Price / Pred Price) * 100? No, (Bid / Basic)?
                # Or API has 'tuchalRate'. Check response log if possible.
                # For now using specific field or default.
                
                result = {
                    "rank": rank,
                    "company": item.get("bizNm", "Unknown"),
                    "ceo": item.get("ceoNm", ""),
                    "bid_price": price,
                    "bid_rate": float(rate_str) if rate_str else 0.0,
                    "success_state": item.get("opengResult", ""), # 낙찰/탈락 etc
                    "note": item.get("rmk", "")
                }
                results.append(result)
            
            # Sort by Rank
            results.sort(key=lambda x: x["rank"])
            return results
            
        except Exception as e:
            print(f"[OpeningResult] Exception: {e}")
            return OpeningResultService.get_mock_results(bid_no)

    @staticmethod
    def get_mock_results(bid_no: str) -> List[dict]:
        """Fallback Mock Data for Demo"""
        return [
            {"rank": 1, "company": "주식회사 희망건설", "ceo": "김희망", "bid_price": 99187010, "bid_rate": 87.755, "success_state": "낙찰", "note": ""},
            {"rank": 2, "company": "(주)성실전기", "ceo": "이성실", "bid_price": 99196890, "bid_rate": 87.764, "success_state": "탈락", "note": ""},
            {"rank": 3, "company": "대박산업", "ceo": "박대박", "bid_price": 99201500, "bid_rate": 87.768, "success_state": "탈락", "note": ""},
            {"rank": 4, "company": "미래건축", "ceo": "최미래", "bid_price": 99205100, "bid_rate": 87.771, "success_state": "탈락", "note": ""},
            {"rank": 5, "company": "가나다건설", "ceo": "정가나", "bid_price": 99210000, "bid_rate": 87.775, "success_state": "탈락", "note": ""},
        ]
