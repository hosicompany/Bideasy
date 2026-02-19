"""
조달청 나라장터 API 연동 서비스
- 낙찰정보 조회
- 입찰공고 조회
- 데이터 수집 및 저장
"""

import httpx
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
import asyncio

logger = logging.getLogger(__name__)

class G2BApiService:
    """조달청 나라장터 Open API 서비스"""
    
    # API 기본 URL (https 필수)
    BASE_URL = "https://apis.data.go.kr/1230000"
    
    # 서비스별 엔드포인트 (일부 서비스는 /as 경로 필요)
    ENDPOINTS = {
        # 낙찰현황서비스 (/as 경로 필요!) - 2026-02-09 확인됨
        "bid_status_goods": "/as/ScsbidInfoService/getScsbidListSttusThng",  # 물품 낙찰현황
        "bid_status_construction": "/as/ScsbidInfoService/getScsbidListSttusCnstwk",  # 공사 낙찰현황
        "bid_status_service": "/as/ScsbidInfoService/getScsbidListSttusServc",  # 용역 낙찰현황
        
        # 낙찰정보서비스 (TODO: 정확한 URL 확인 필요)
        "bid_result_goods": "/BidResultInfoService/getBidResultListInfoThngPPSSrch",  # 물품
        "bid_result_service": "/BidResultInfoService/getBidResultListInfoServcPPSSrch",  # 용역
        "bid_result_construction": "/BidResultInfoService/getBidResultListInfoCnstwkPPSSrch",  # 공사
        "bid_result_foreign": "/BidResultInfoService/getBidResultListInfoFrgcptPPSSrch",  # 외자
        
        # 입찰공고정보서비스 (TODO: 정확한 URL 확인 필요)
        "bid_notice_goods": "/BidPublicInfoService/getBidPblancListInfoThngPPSSrch",  # 물품
        "bid_notice_service": "/BidPublicInfoService/getBidPblancListInfoServcPPSSrch",  # 용역
        "bid_notice_construction": "/BidPublicInfoService/getBidPblancListInfoCnstwkPPSSrch",  # 공사
    }
    
    def __init__(self, api_key: str):
        """
        Args:
            api_key: 공공데이터포털 API 인증키
        """
        self.api_key = api_key
        self.client = httpx.AsyncClient(timeout=30.0)
    
    async def close(self):
        """HTTP 클라이언트 종료"""
        await self.client.aclose()
    
    async def _request(
        self,
        endpoint: str,
        params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        API 요청 공통 메서드
        
        Args:
            endpoint: API 엔드포인트
            params: 요청 파라미터
            
        Returns:
            API 응답 데이터
        """
        url = f"{self.BASE_URL}{endpoint}"
        
        # 기본 파라미터 추가
        params.update({
            "serviceKey": self.api_key,
            "type": "json",
            "numOfRows": params.get("numOfRows", 100),
            "pageNo": params.get("pageNo", 1),
        })
        
        try:
            response = await self.client.get(url, params=params)
            response.raise_for_status()
            
            data = response.json()
            
            # 응답 구조 확인
            if "response" in data:
                return data["response"]
            return data
            
        except httpx.HTTPError as e:
            logger.error(f"API 요청 실패: {e}")
            raise
        except Exception as e:
            logger.error(f"예상치 못한 오류: {e}")
            raise
    
    async def get_bid_results(
        self,
        bid_type: str = "goods",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        num_of_rows: int = 100,
        page_no: int = 1
    ) -> Dict[str, Any]:
        """
        낙찰정보 조회
        
        Args:
            bid_type: 입찰 유형 (goods, service, construction, foreign)
            start_date: 조회 시작일 (YYYYMMDD)
            end_date: 조회 종료일 (YYYYMMDD)
            num_of_rows: 한 페이지 결과 수
            page_no: 페이지 번호
            
        Returns:
            낙찰정보 목록
        """
        endpoint_key = f"bid_result_{bid_type}"
        endpoint = self.ENDPOINTS.get(endpoint_key)
        
        if not endpoint:
            raise ValueError(f"지원하지 않는 입찰 유형: {bid_type}")
        
        # 기본 날짜 설정 (최근 30일)
        if not end_date:
            end_date = datetime.now().strftime("%Y%m%d")
        if not start_date:
            start_date = (datetime.now() - timedelta(days=30)).strftime("%Y%m%d")
        
        params = {
            "inqryBgnDt": start_date,
            "inqryEndDt": end_date,
            "numOfRows": num_of_rows,
            "pageNo": page_no,
        }
        
        return await self._request(endpoint, params)
    
    async def get_bid_result_detail(
        self,
        bid_type: str,
        bid_ntce_no: str,
        bid_ntce_ord: str = "00"
    ) -> Dict[str, Any]:
        """
        낙찰정보 상세 조회 (복수예비가격 포함)
        
        Args:
            bid_type: 입찰 유형
            bid_ntce_no: 입찰공고번호
            bid_ntce_ord: 입찰공고차수
            
        Returns:
            낙찰 상세 정보
        """
        # 상세 조회 엔드포인트 (업무별로 다름)
        detail_endpoints = {
            "goods": "/BidResultInfoService/getBidResultListInfoThngOpengResultInfo",
            "service": "/BidResultInfoService/getBidResultListInfoServcOpengResultInfo",
            "construction": "/BidResultInfoService/getBidResultListInfoCnstwkOpengResultInfo",
        }
        
        endpoint = detail_endpoints.get(bid_type)
        if not endpoint:
            raise ValueError(f"상세 조회 미지원 유형: {bid_type}")
        
        params = {
            "bidNtceNo": bid_ntce_no,
            "bidNtceOrd": bid_ntce_ord,
        }
        
        return await self._request(endpoint, params)
    
    async def get_preliminary_prices(
        self,
        bid_type: str,
        bid_ntce_no: str,
        bid_ntce_ord: str = "00"
    ) -> List[Dict[str, Any]]:
        """
        복수예비가격 조회
        
        Args:
            bid_type: 입찰 유형
            bid_ntce_no: 입찰공고번호
            bid_ntce_ord: 입찰공고차수
            
        Returns:
            복수예비가격 목록 (15개)
        """
        # 복수예비가격 엔드포인트
        prelim_endpoints = {
            "goods": "/BidResultInfoService/getBidResultListInfoThngPreparPrceInfo",
            "service": "/BidResultInfoService/getBidResultListInfoServcPreparPrceInfo",
            "construction": "/BidResultInfoService/getBidResultListInfoCnstwkPreparPrceInfo",
        }
        
        endpoint = prelim_endpoints.get(bid_type)
        if not endpoint:
            raise ValueError(f"복수예비가격 조회 미지원 유형: {bid_type}")
        
        params = {
            "bidNtceNo": bid_ntce_no,
            "bidNtceOrd": bid_ntce_ord,
        }
        
        result = await self._request(endpoint, params)
        
        # 응답에서 예비가격 목록 추출
        body = result.get("body", {})
        items = body.get("items", [])
        
        if isinstance(items, dict):
            items = items.get("item", [])
        
        return items if isinstance(items, list) else [items] if items else []
    
    async def get_bid_status(
        self,
        bid_type: str = "goods",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        num_of_rows: int = 100,
        page_no: int = 1
    ) -> Dict[str, Any]:
        """
        낙찰정보 현황 조회 (개찰결과 포함)
        
        Args:
            bid_type: 입찰 유형 (goods, service, construction)
            start_date: 조회 시작일 (YYYYMMDD)
            end_date: 조회 종료일 (YYYYMMDD)
            num_of_rows: 한 페이지 결과 수
            page_no: 페이지 번호
            
        Returns:
            낙찰정보 현황 목록
        """
        endpoint_key = f"bid_status_{bid_type}"
        endpoint = self.ENDPOINTS.get(endpoint_key)
        
        if not endpoint:
            raise ValueError(f"지원하지 않는 입찰 유형: {bid_type}")
        
        # 기본 날짜 설정 (최근 30일)
        if not end_date:
            end_date = datetime.now().strftime("%Y%m%d")
        if not start_date:
            start_date = (datetime.now() - timedelta(days=30)).strftime("%Y%m%d")
        
        # 날짜 형식 변환 (YYYYMMDD -> YYYYMMDDHHmm)
        if len(start_date) == 8:
            start_date = start_date + "0000"
        if len(end_date) == 8:
            end_date = end_date + "2359"
        
        params = {
            "inqryDiv": "1",  # 조회구분 (필수)
            "inqryBgnDt": start_date,
            "inqryEndDt": end_date,
            "numOfRows": num_of_rows,
            "pageNo": page_no,
        }
        
        return await self._request(endpoint, params)
    
    async def get_bid_status_all(
        self,
        bid_type: str = "goods",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        batch_size: int = 100
    ) -> List[Dict[str, Any]]:
        """
        낙찰정보 현황 전체 조회 (페이징 자동 처리)
        
        Args:
            bid_type: 입찰 유형 (goods, service, construction)
            start_date: 조회 시작일 (YYYYMMDD)
            end_date: 조회 종료일 (YYYYMMDD)
            batch_size: 배치당 건수 (최대 999)
            
        Returns:
            낙찰정보 현황 전체 목록
        """
        all_results = []
        page_no = 1
        
        while True:
            try:
                result = await self.get_bid_status(
                    bid_type=bid_type,
                    start_date=start_date,
                    end_date=end_date,
                    num_of_rows=batch_size,
                    page_no=page_no
                )
                
                body = result.get("body", {})
                items = body.get("items", [])
                
                if isinstance(items, dict):
                    items = items.get("item", [])
                
                if not items:
                    break
                
                all_results.extend(items if isinstance(items, list) else [items])
                
                # 다음 페이지 확인
                total_count = int(body.get("totalCount", 0))
                if page_no * batch_size >= total_count:
                    break
                
                page_no += 1
                await asyncio.sleep(0.3)  # API 호출 제한 준수
                
            except Exception as e:
                logger.error(f"낙찰정보 현황 조회 오류: {e}")
                break
        
        logger.info(f"낙찰정보 현황 총 {len(all_results)}건 조회 완료")
        return all_results
    
    async def get_opening_results(
        self,
        bid_type: str = "goods",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        num_of_rows: int = 100,
        page_no: int = 1
    ) -> Dict[str, Any]:
        """
        개찰결과 조회 (낙찰정보 현황 API 활용)
        
        테스트에서 5,362건 조회 성공한 것과 동일한 패턴
        
        Args:
            bid_type: 입찰 유형 (goods, service, construction)
            start_date: 조회 시작일 (YYYYMMDD)
            end_date: 조회 종료일 (YYYYMMDD)
            num_of_rows: 한 페이지 결과 수 (최대 999)
            page_no: 페이지 번호
            
        Returns:
            개찰결과 목록
        """
        # 개찰결과는 낙찰정보 현황 API를 사용
        return await self.get_bid_status(
            bid_type=bid_type,
            start_date=start_date,
            end_date=end_date,
            num_of_rows=num_of_rows,
            page_no=page_no
        )
    
    async def collect_historical_data(
        self,
        bid_type: str = "goods",
        months: int = 12,
        batch_size: int = 100
    ) -> List[Dict[str, Any]]:
        """
        과거 낙찰 데이터 대량 수집
        
        Args:
            bid_type: 입찰 유형
            months: 수집할 개월 수
            batch_size: 배치당 건수
            
        Returns:
            수집된 낙찰정보 목록
        """
        all_results = []
        end_date = datetime.now()
        
        for i in range(months):
            start_date = end_date - timedelta(days=30)
            
            logger.info(f"수집 중: {start_date.strftime('%Y-%m-%d')} ~ {end_date.strftime('%Y-%m-%d')}")
            
            page_no = 1
            while True:
                try:
                    result = await self.get_bid_results(
                        bid_type=bid_type,
                        start_date=start_date.strftime("%Y%m%d"),
                        end_date=end_date.strftime("%Y%m%d"),
                        num_of_rows=batch_size,
                        page_no=page_no
                    )
                    
                    body = result.get("body", {})
                    items = body.get("items", [])
                    
                    if isinstance(items, dict):
                        items = items.get("item", [])
                    
                    if not items:
                        break
                    
                    all_results.extend(items if isinstance(items, list) else [items])
                    
                    # 다음 페이지 확인
                    total_count = int(body.get("totalCount", 0))
                    if page_no * batch_size >= total_count:
                        break
                    
                    page_no += 1
                    await asyncio.sleep(0.5)  # API 호출 제한 준수
                    
                except Exception as e:
                    logger.error(f"데이터 수집 오류: {e}")
                    break
            
            end_date = start_date
            await asyncio.sleep(1)  # 월간 데이터 수집 간 대기
        
        logger.info(f"총 {len(all_results)}건 수집 완료")
        return all_results


# 싱글톤 인스턴스 (API 키는 설정에서 주입)
_g2b_service: Optional[G2BApiService] = None

def get_g2b_service(api_key: str) -> G2BApiService:
    """G2B API 서비스 인스턴스 반환"""
    global _g2b_service
    if _g2b_service is None:
        _g2b_service = G2BApiService(api_key)
    return _g2b_service
