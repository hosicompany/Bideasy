# -*- coding: utf-8 -*-
"""
Bid Detail Service - Fetches bid details from Public Data Portal API
Uses getDataSetOpnStdBidPblancInfo endpoint
"""
import requests
import json
from typing import Optional, Dict
from app.core.config import settings

class BidDetailService:
    """Service to fetch detailed bid information from Public Data Portal API."""
    
    # API Endpoint for detailed bid info
    BASE_URL = "https://apis.data.go.kr/1230000/PubDataOpnStdService/getDataSetOpnStdBidPblancInfo"
    
    @staticmethod
    def fetch_bid_detail(bid_ntce_no: str, bid_ntce_ord: str = "00") -> Optional[Dict]:
        """
        Fetch detailed bid information from Public Data Portal API.
        
        Args:
            bid_ntce_no: Bid notice number (e.g., "R25BK01250181")
            bid_ntce_ord: Bid notice order (e.g., "000" or "00")
        
        Returns:
            Dictionary containing bid details or None if not found
        """
        params = {
            "serviceKey": settings.PUBLIC_DATA_KEY,
            "numOfRows": 10,
            "pageNo": 1,
            "type": "json",
            "bidNtceNo": bid_ntce_no,
        }
        
        try:
            print(f"[BidDetail] Fetching details for: {bid_ntce_no}", flush=True)
            response = requests.get(BidDetailService.BASE_URL, params=params, timeout=15)
            
            if response.status_code != 200:
                print(f"[BidDetail] HTTP Error: {response.status_code}")
                return None
            
            try:
                data = response.json()
            except json.JSONDecodeError:
                print(f"[BidDetail] JSON Decode Error: {response.text[:200]}")
                return None
            
            # Parse response
            body = data.get("response", {}).get("body", {})
            items = body.get("items", [])
            
            if not items:
                print(f"[BidDetail] No items found for {bid_ntce_no}")
                return None
            
            # Handle single item case (API sometimes returns dict instead of list)
            if isinstance(items, dict):
                items = [items]
            
            # Find matching bid by order
            for item in items:
                if item.get("bidNtceOrd", "") == bid_ntce_ord or bid_ntce_ord == "00":
                    print(f"[BidDetail] Found: {item.get('bidNtceNm', 'N/A')[:50]}", flush=True)
                    return BidDetailService._format_bid_detail(item)
            
            # Return first item if no exact match
            if items:
                return BidDetailService._format_bid_detail(items[0])
            
            return None
            
        except Exception as e:
            print(f"[BidDetail] Error: {e}")
            return None
    
    @staticmethod
    def _format_bid_detail(item: Dict) -> Dict:
        """Format API response into a structured dictionary for LLM analysis."""
        return {
            "bid_no": f"{item.get('bidNtceNo', '')}-{item.get('bidNtceOrd', '000')}",
            "title": item.get("bidNtceNm", ""),
            "announcement_date": item.get("bidNtceDt", ""),
            "opening_date": item.get("opengDt", ""),
            "estimated_price": item.get("presmptPrce", 0),
            "budget_amount": item.get("asignBdgtAmt", 0),
            "organization": item.get("ntceInsttNm", ""),
            "demand_organization": item.get("dmndInsttNm", ""),
            "contract_method": item.get("cntrctMthdNm", ""),
            "bid_method": item.get("bidMthdNm", ""),
            "qualification": item.get("bidQlfctRgstDt", ""),
            "region": item.get("ppncRgnNm", ""),
            "bid_type": item.get("bidClsfcNm", ""),
            "notice_type": item.get("ntceSttusNm", ""),
            "international_bid": item.get("intrntnlBidYn", "N"),
            "joint_contract": item.get("jntcontrctPsbltyYn", "N"),
            "raw_data": item  # Keep full data for debugging
        }
    
    @staticmethod
    def get_analysis_context(bid_detail: Dict) -> str:
        """Convert bid detail to text context for LLM analysis."""
        if not bid_detail:
            return ""
        
        lines = [
            f"공고명: {bid_detail.get('title', 'N/A')}",
            f"공고기관: {bid_detail.get('organization', 'N/A')}",
            f"수요기관: {bid_detail.get('demand_organization', 'N/A')}",
            f"추정가격: {bid_detail.get('estimated_price', 0):,.0f}원",
            f"배정예산: {bid_detail.get('budget_amount', 0):,.0f}원",
            f"계약방법: {bid_detail.get('contract_method', 'N/A')}",
            f"입찰방법: {bid_detail.get('bid_method', 'N/A')}",
            f"공고일: {bid_detail.get('announcement_date', 'N/A')}",
            f"개찰일: {bid_detail.get('opening_date', 'N/A')}",
            f"지역: {bid_detail.get('region', 'N/A')}",
            f"입찰구분: {bid_detail.get('bid_type', 'N/A')}",
            f"국제입찰여부: {bid_detail.get('international_bid', 'N')}",
            f"공동계약가능: {bid_detail.get('joint_contract', 'N')}",
        ]
        
        return "\n".join(lines)
