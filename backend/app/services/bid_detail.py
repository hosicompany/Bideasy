# -*- coding: utf-8 -*-
"""
Bid Detail Service - Fetches bid details from Public Data Portal API
Uses getDataSetOpnStdBidPblancInfo endpoint
"""
import requests
import json
from typing import Optional, Dict
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

class BidDetailService:
    """Service to fetch detailed bid information from Public Data Portal API."""

    # API Endpoint for detailed bid info
    BASE_URL = "https://apis.data.go.kr/1230000/PubDataOpnStdService/getDataSetOpnStdBidPblancInfo"

    # BidPublicInfoService 목록 3종 (공사/용역/물품).
    # bidNtceNo + inqryDiv=2(공고번호 검색) 로 단건 직접조회 가능 (prod 라이브 확정 2026-05-30).
    _SEARCH_BASE = "https://apis.data.go.kr/1230000/ad/BidPublicInfoService"
    _SEARCH_ENDPOINTS = [
        ("construction", "/getBidPblancListInfoCnstwk"),
        ("service", "/getBidPblancListInfoServc"),
        ("goods", "/getBidPblancListInfoThng"),
    ]

    @staticmethod
    def _fetch_by_bidno_search(bid_ntce_no: str) -> Optional[Dict]:
        """공고번호 직접검색 (inqryDiv=2) — 공사→용역→물품 순차 시도.

        스파이크(prod 라이브) 확정: BidPublicInfoService 3종에
        {bidNtceNo, inqryDiv:2} 주입 시 total=1 단건 정확 반환.
        카테고리를 모르므로 3개 순차 시도, 먼저 매칭되는 것 채택.
        500나는 표준데이터셋·100건 윈도우 스캔보다 신뢰도 높음 → 1순위.
        """
        base = bid_ntce_no.split("-")[0] if "-" in bid_ntce_no else bid_ntce_no
        for cat, path in BidDetailService._SEARCH_ENDPOINTS:
            params = {
                "serviceKey": settings.PUBLIC_DATA_KEY,
                "numOfRows": 10,
                "pageNo": 1,
                "type": "json",
                "inqryDiv": 2,          # 2 = 공고번호 검색 모드 (핵심)
                "bidNtceNo": base,
            }
            try:
                resp = requests.get(
                    BidDetailService._SEARCH_BASE + path, params=params, timeout=15
                )
                if resp.status_code != 200:
                    logger.info(f"[bidno-search] {cat} HTTP {resp.status_code}")
                    continue
                items = resp.json().get("response", {}).get("body", {}).get("items", [])
                if isinstance(items, dict):
                    items = [items]
                if not items:
                    continue
                # 정확 일치 우선, 없으면 첫 항목
                for it in items:
                    if it.get("bidNtceNo") == base:
                        logger.info(f"[bidno-search] MATCH {cat}: {it.get('bidNtceNm','')[:30]}")
                        return BidDetailService._format_bid_detail(it)
                logger.info(f"[bidno-search] {cat}: items but no exact bidNtceNo match")
                return BidDetailService._format_bid_detail(items[0])
            except Exception as e:
                logger.warning(f"[bidno-search] {cat} error: {e}")
                continue
        return None

    @staticmethod
    def fetch_bid_detail_robust(bid_ntce_no: str, bid_ntce_ord: str = "00") -> Optional[Dict]:
        """
        단건 공고 조회 — 우선순위:
          1) 공고번호 직접검색 (inqryDiv=2, 공사/용역/물품) ← prod 라이브 확정, 신뢰도 1순위
          2) 표준데이터셋 primary (getDataSetOpnStdBidPblancInfo) ← 종종 500
          3) 공사 목록 100건 스캔 (구 fallback) ← 윈도우·카테고리 한계
        """
        # 1순위: 공고번호 직접검색
        result = BidDetailService._fetch_by_bidno_search(bid_ntce_no)
        if result:
            return result

        # 2순위: 기존 primary (표준데이터셋) — 호환 유지
        logger.info("bidno-search 실패 → primary(표준데이터셋) 시도")
        result = BidDetailService.fetch_bid_detail(bid_ntce_no, bid_ntce_ord)
        if result:
            return result

        # 3순위: 구 fallback (공사 목록 100건 스캔)
        logger.warning("Primary 도 None → 구 list fallback 시도")
        clean_bid_no = bid_ntce_no.split("-")[0] if "-" in bid_ntce_no else bid_ntce_no
        return BidDetailService._fetch_from_list_api(clean_bid_no)

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
            logger.info(f"Fetching details for: {bid_ntce_no}")
            response = requests.get(BidDetailService.BASE_URL, params=params, timeout=15)
            
            if response.status_code != 200:
                logger.error(f"HTTP Error: {response.status_code}")
                # Don't return None here, raise exception to trigger fallback
                raise Exception(f"HTTP Error {response.status_code}")
            
            try:
                data = response.json()
            except json.JSONDecodeError:
                logger.error(f"JSON Decode Error: {response.text[:200]}")
                return None
            
            # Parse response
            body = data.get("response", {}).get("body", {})
            items = body.get("items", [])
            
            if not items:
                logger.info(f"No items found for {bid_ntce_no}")
                return None
            
            # Handle single item case (API sometimes returns dict instead of list)
            if isinstance(items, dict):
                items = [items]
            
            # Find matching bid by order
            for item in items:
                if item.get("bidNtceOrd", "") == bid_ntce_ord or bid_ntce_ord == "00":
                    logger.info(f"Found: {item.get('bidNtceNm', 'N/A')[:50]}")
                    return BidDetailService._format_bid_detail(item)
            
            # Return first item if no exact match
            if items:
                return BidDetailService._format_bid_detail(items[0])
            
            return None
            
        except Exception as e:
            logger.error(f"Error: {e}")
            
        logger.warning("Primary API failed. Trying Fallback (List API - Construction)...")
        return BidDetailService._fetch_from_list_api(bid_ntce_no)

    @staticmethod
    def _fetch_from_list_api(bid_ntce_no: str) -> Optional[Dict]:
        """Fallback: Fetch from Construction List API (Client-side filtering)"""
        url = "https://apis.data.go.kr/1230000/ad/BidPublicInfoService/getBidPblancListInfoCnstwk"
        
        # Recent 30 days (API fails if we send bidNtceNo param, so we fetch list and filter)
        from datetime import datetime, timedelta
        end_date = datetime.now()
        start_date = end_date - timedelta(days=30)
        
        params = {
            "serviceKey": settings.PUBLIC_DATA_KEY,
            "numOfRows": 100, # Fetch enough to find it
            "pageNo": 1,
            "inqryDiv": 1,
            "inqryBgnDt": start_date.strftime("%Y%m%d0000"),
            "inqryEndDt": end_date.strftime("%Y%m%d2359"),
            "type": "json"
            # bidNtceNo param removed because it causes 0 results
        }
        
        try:
            logger.info(f"Fallback: Fetching list (30 days) to find {bid_ntce_no}...")
            response = requests.get(url, params=params, timeout=20)
            if response.status_code != 200:
                logger.error(f"Fallback HTTP Error: {response.status_code}")
                return None
                
            data = response.json()
            items = data.get("response", {}).get("body", {}).get("items", [])
            
            if isinstance(items, dict):
                items = [items]
            
            # Client-side Filter
            for item in items:
                if item.get("bidNtceNo") == bid_ntce_no:
                    logger.info(f"Found via Fallback List: {item.get('bidNtceNm', 'N/A')[:30]}")
                    return BidDetailService._format_bid_detail(item)
                    
            logger.warning(f"Fallback: {bid_ntce_no} not found in recent {len(items)} items.")
                
        except Exception as e:
            logger.error(f"Fallback Error: {e}")
            
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
