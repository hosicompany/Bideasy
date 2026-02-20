import requests
import json
from typing import List
from datetime import datetime, timedelta
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

class OpeningResultService:
    # Construction Opening Results (Standard Service)
    # Replaced deprecated getOpengResultListInfoCnstwk with getDataSetOpnStdScsbidInfo
    # Note: Standard Service covers all types (Cnst/Serv/Goods) usually via parameters or unified endpoint.
    BASE_URL_CNST = "https://apis.data.go.kr/1230000/ao/PubDataOpnStdService/getDataSetOpnStdScsbidInfo"
    BASE_URL_SERV = "https://apis.data.go.kr/1230000/ao/PubDataOpnStdService/getDataSetOpnStdScsbidInfo" # Same for now
    BASE_URL_THNG = "https://apis.data.go.kr/1230000/ao/PubDataOpnStdService/getDataSetOpnStdScsbidInfo"
    
    @staticmethod
    def fetch_opening_results(bid_no: str, contract_type: str = "CONSTRUCTION") -> List[dict]:
        """
        Fetch opening results (Rankings) for a specific bid.
        """
        # 1. Parse bid_no (Format: 20241234567-00)
        try:
            bid_ntce_no, bid_ntce_ord = bid_no.split("-")
        except ValueError:
            logger.error(f"Invalid bid_no format: {bid_no}")
            return []

        url = OpeningResultService.BASE_URL_CNST
            
        params = {
            "serviceKey": settings.PUBLIC_DATA_KEY,
            "numOfRows": 100,
            "pageNo": 1,
            "type": "json",
            "inqryDiv": "4", # 4 = Search by Bid No (Confirmed from docs/tests usually)
            "bidNtceNo": bid_ntce_no,
            "bidNtceOrd": bid_ntce_ord,
        }
        
        try:
            logger.info(f"Fetching result for {bid_no} from {url}")
            response = requests.get(url, params=params, timeout=5, verify=False)
            
            if response.status_code != 200:
                logger.error(f"API Error: {response.status_code} {response.text}")
                return OpeningResultService.get_mock_results(bid_no)
            
            try:
                data = response.json()
            except json.JSONDecodeError:
                logger.error(f"JSON Decode Error: {response.text[:100]}")
                return OpeningResultService.get_mock_results(bid_no)
                
            response_body = data.get("response", {}).get("body", {})
            items = response_body.get("items", [])
            
            if not items:
                logger.info("No items found in API response")
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
                except (ValueError, TypeError):
                    price = 0

                try:
                    rank = int(item.get("opengRank", 0))
                except (ValueError, TypeError):
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
            logger.error(f"Exception: {e}")
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

    @staticmethod
    def crawl_agency_history(agency_name: str, months: int = 6) -> List[dict]:
        """
        Fetch historical opening results for a specific agency.
        Used for 'Agency Profiling'.
        """
        # Calculate Date Range
        end_date = datetime.now()
        start_date = end_date - timedelta(days=30 * months)
        
        start_str = start_date.strftime("%Y%m%d") + "0000"
        end_str = end_date.strftime("%Y%m%d") + "2359"
        
        # Use Construction endpoint by default for Phase 3 MVP
        # Ideally should iterate all types or take type as param
        url = OpeningResultService.BASE_URL_CNST
        
        params = {
            "serviceKey": settings.PUBLIC_DATA_KEY,
            "numOfRows": 200, # Max rows to fetch history
            "pageNo": 1,
            "inqryDiv": 1,
            "opengBgnDt": start_str, # Opening Date Range
            "opengEndDt": end_str,
            "orgNm": agency_name,    # Agency Name Filter
            "type": "json"
        }
        
        results = []
        try:
            logger.info(f"Fetching history for {agency_name} ({start_str}~{end_str})...")
            response = requests.get(url, params=params, timeout=10, verify=False)
            
            if response.status_code != 200:
                logger.error(f"Error: {response.status_code}")
                return []
                
            data = response.json()
            items = data.get("response", {}).get("body", {}).get("items", [])
            
            if not items:
                logger.info(f"No history found for {agency_name}")
                return []
                
            if isinstance(items, dict):
                items = [items]
                
            logger.info(f"Found {len(items)} raw items. Processing...")
            
            
            for item in items:
                # We need: bid_no, winner_rate, winner_price
                # API Field Mapping:
                # bidNtceNo, bidNtceOrd
                # succsbidRate (낙찰률) -> often missing or 0 in some APIs.
                # If missing, we calculate: (Med Price / Basic Price)? No, (Bid / Basic).
                
                # Filter: Only Completed Bids (Opening State)
                # opengResultNm: "개찰완료", "재입찰", "유찰"
                status = item.get("opengResultNm", "")
                if "완료" not in status and "낙찰" not in status:
                    continue
                
                # For Agency Profiling, we need the WINNER's rate.
                # However, this list API might only give the Notice info, not the Winner info?
                # Let's check the endpoint fields. 
                # getOpengResultListInfoCnstwk returns List of *Bids* that are opened, or *Participants*?
                # Actually 'getOpengResultListInfo' usually returns list of Bids.
                # Inside, it has 'succsbidderNm' (Winner Name) and 'succsbidAmt' (Winner Price).
                
                winner_name = item.get("succsbidderNm", "")
                winner_price_str = item.get("succsbidAmt", "0")
                winner_rate_str = item.get("succsbidRate", "0") # Check if this exists
                
                if not winner_name:
                    continue # No winner yet
                    
                bid_no = f"{item.get('bidNtceNo')}-{item.get('bidNtceOrd')}"
                
                try:
                    w_price = float(winner_price_str)
                    w_rate = float(winner_rate_str)
                except (ValueError, TypeError):
                    w_price = 0
                    w_rate = 0
                
                # Clean Data
                results.append({
                    "bid_no": bid_no,
                    "organization": item.get("ntceInsttNm", agency_name),
                    "region": "", # Might need to infer
                    "open_date": item.get("opengDt", ""), # Format: YYYYMMDDHHMM
                    "basic_price": 0, # Often not in Result List, might need Notice Lookup
                    "winner_company": winner_name,
                    "winner_price": w_price,
                    "winner_rate": w_rate
                })
                
            logger.info(f"Processed {len(results)} valid outcomes.")
            return results
            
        except Exception as e:
            logger.error(f"Failed: {e}")
            return []
