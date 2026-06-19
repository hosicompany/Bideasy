import requests
from bs4 import BeautifulSoup
import re
import asyncio
import aiohttp
from typing import List, Dict, Optional
from app.core.logging import get_logger
from app.core.url_guard import is_safe_public_url

logger = get_logger(__name__)

# ──────────────────────────────────────────────────────────────────────
# ⚠️ A값 수집 경로 우선순위 (DOM 의존도 축소 리팩터, 판정 C)
#
# A값(사후정산 비목 = 국민연금·건강보험·노인장기요양·산재·고용보험 등)은
# 조달청 OpenAPI 입찰공고/낙찰정보 서비스에 **구조화 필드로 존재하지 않음**.
# (getDataSetOpnStdBidPblancInfo, getBidPblancListInfoCnstwk 모두 미제공)
#
#   1순위(주 경로): 익스텐션이 g2b 상세 DOM(data-title="A값")에서 추출해
#                   투찰가 계산 API 에 직접 주입. (extractor.ts)
#   2순위(LAST-RESORT fallback): 아래 ScraperService 가 서버에서 g2b 페이지를
#                   재스크래핑 + 정규식. ⚠️ 차세대 나라장터 인증 강화 시
#                   서버 재스크래핑이 로그인월에 막힐 수 있어 신뢰 불가.
#                   따라서 이 경로는 익스텐션이 A값을 못 올린 경우의 보조용.
#
# → 이 모듈은 삭제하지 않고 fallback 으로 보존. 단 주 경로는 익스텐션 DOM.
# ──────────────────────────────────────────────────────────────────────

class ScraperService:

    # Location keywords to extract from content
    LOCATION_PATTERNS = [
        r"공사지역\s*[:：]\s*([가-힣\s]+)",
        r"납품장소\s*[:：]\s*([가-힣\s]+)",
        r"사업장소\s*[:：]\s*([가-힣\s]+)",
        r"지역\s*[:：]\s*([가-힣\s]+)",
        r"소재지\s*[:：]\s*([가-힣\s]+)"
    ]
    
    # A-value (고정비용) extraction patterns
    # 국민연금, 건강보험, 노인장기요양, 퇴직공제, 산재보험, 고용보험 등
    A_VALUE_PATTERNS = [
        # Pattern: "국민연금보험료 : 1,234,567" or "국민연금 1234567원"
        (r"국민연금(?:보험료)?\s*[:：]?\s*([\d,]+)", "국민연금"),
        (r"건강보험(?:료)?\s*[:：]?\s*([\d,]+)", "건강보험"),
        (r"노인장기요양(?:보험료)?\s*[:：]?\s*([\d,]+)", "노인장기요양"),
        (r"퇴직공제(?:부금)?\s*[:：]?\s*([\d,]+)", "퇴직공제"),
        (r"산재보험(?:료)?\s*[:：]?\s*([\d,]+)", "산재보험"),
        (r"고용보험(?:료)?\s*[:：]?\s*([\d,]+)", "고용보험"),
        # Generic "A값" pattern
        (r"A\s*값\s*[:：]?\s*([\d,]+)", "A값"),
        (r"에이값\s*[:：]?\s*([\d,]+)", "A값"),
    ]
    
    # Net Cost (순공사원가) patterns
    NET_COST_PATTERNS = [
        r"순공사원가\s*[:：]?\s*([\d,]+)",
        r"순공사비\s*[:：]?\s*([\d,]+)",
    ]
    
    @staticmethod
    def fetch_page_content(url: str) -> str:
        """
        Fetch HTML from URL and extract relevant text for LLM context.
        Targeting G2B specific structure.
        """
        # SSRF 가드: 화이트리스트 도메인 + 공인 IP 만 허용 (내부망·메타데이터 차단)
        if not is_safe_public_url(url):
            logger.warning(f"fetch_page_content blocked unsafe url: {url!r}")
            return ""

        try:
            # User-Agent is required for some sites
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            }

            # 1. Verification Bypass (Optional, G2B sometimes requires SSL verify=False)
            #    allow_redirects=False 로 리다이렉트를 통한 화이트리스트 우회 차단.
            response = requests.get(url, headers=headers, verify=False, timeout=5, allow_redirects=False)
            response.encoding = 'utf-8' # G2B is usually utf-8 or euc-kr
            
            if response.status_code != 200:
                logger.error(f"Failed to fetch {url}: {response.status_code}")
                return ""

            # 2. Parse HTML
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # 3. Extract Core Content (Heuristic)
            content_text = ""
            
            # G2B Specific Selectors (Common patterns)
            target_selectors = [
                 ".table_list", # Common table class
                 "#container",  # Main container
                 ".section"
            ]
            
            found = False
            for selector in target_selectors:
                elements = soup.select(selector)
                if elements:
                    for el in elements:
                        content_text += el.get_text(separator="\n", strip=True) + "\n"
                    found = True
            
            # Fallback: Body text if no selectors matched
            if not found:
                content_text = soup.body.get_text(separator="\n", strip=True)

            # 4. Cleanup
            cleaned_text = re.sub(r'\n\s*\n', '\n', content_text)
            
            # Limit length for LLM Token limit (e.g. 5000 chars)
            return cleaned_text[:5000]

        except Exception as e:
            logger.error(f"Error scraping {url}: {e}")
            return ""
    
    @staticmethod
    def extract_location(content: str) -> Optional[str]:
        """Extract location/region from scraped content."""
        if not content:
            return None
        for pattern in ScraperService.LOCATION_PATTERNS:
            match = re.search(pattern, content)
            if match:
                return match.group(1).strip()
        return None
    
    @staticmethod
    def extract_a_value(content: str) -> Dict[str, any]:
        """
        A값(고정비용) 추출: 국민연금, 건강보험, 노인장기요양 등
        
        Returns:
            {
                "total": 합계 금액 (int),
                "breakdown": {"국민연금": 1234, "건강보험": 5678, ...},
                "found": 추출 성공 여부 (bool)
            }
        """
        if not content:
            return {"total": 0, "breakdown": {}, "found": False}
        
        breakdown = {}
        total = 0
        
        for pattern, name in ScraperService.A_VALUE_PATTERNS:
            match = re.search(pattern, content)
            if match:
                # "1,234,567" -> 1234567
                value_str = match.group(1).replace(",", "")
                try:
                    value = int(value_str)
                    # 이미 "A값" 자체를 찾았으면 그게 총합
                    if name == "A값":
                        return {"total": value, "breakdown": {"A값": value}, "found": True}
                    breakdown[name] = value
                    total += value
                except ValueError:
                    continue
        
        return {
            "total": total,
            "breakdown": breakdown,
            "found": total > 0
        }
    
    @staticmethod
    def extract_net_cost(content: str) -> Optional[int]:
        """
        순공사원가 추출 (적격심사 하한선 방어용)
        
        Returns:
            순공사원가 금액 (int) 또는 None
        """
        if not content:
            return None
        
        for pattern in ScraperService.NET_COST_PATTERNS:
            match = re.search(pattern, content)
            if match:
                value_str = match.group(1).replace(",", "")
                try:
                    return int(value_str)
                except ValueError:
                    continue
        return None
    
    @staticmethod
    async def fetch_page_async(session: aiohttp.ClientSession, url: str) -> Dict:
        """Async version of page fetching."""
        # SSRF 가드: 화이트리스트 도메인 + 공인 IP 만 허용
        if not is_safe_public_url(url):
            logger.warning(f"fetch_page_async blocked unsafe url: {url!r}")
            return {"url": url, "content": "", "location": None}

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }

        try:
            async with session.get(url, headers=headers, ssl=False, allow_redirects=False, timeout=aiohttp.ClientTimeout(total=5)) as response:
                if response.status != 200:
                    return {"url": url, "content": "", "location": None}
                
                html = await response.text()
                soup = BeautifulSoup(html, 'html.parser')
                
                content_text = ""
                target_selectors = [".table_list", "#container", ".section"]
                
                found = False
                for selector in target_selectors:
                    elements = soup.select(selector)
                    if elements:
                        for el in elements:
                            content_text += el.get_text(separator="\n", strip=True) + "\n"
                        found = True
                
                if not found and soup.body:
                    content_text = soup.body.get_text(separator="\n", strip=True)
                
                cleaned_text = re.sub(r'\n\s*\n', '\n', content_text)[:5000]
                location = ScraperService.extract_location(cleaned_text)
                
                return {"url": url, "content": cleaned_text, "location": location}
                
        except Exception as e:
            logger.error(f"Async Error: {e}")
            return {"url": url, "content": "", "location": None}
    
    @staticmethod
    async def scrape_batch_async(urls: List[str]) -> List[Dict]:
        """Scrape multiple URLs in parallel."""
        async with aiohttp.ClientSession() as session:
            tasks = [ScraperService.fetch_page_async(session, url) for url in urls]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            # Filter out exceptions
            return [r for r in results if isinstance(r, dict)]
    
    @staticmethod
    def scrape_batch(urls: List[str]) -> List[Dict]:
        """Synchronous wrapper for async batch scraping."""
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        return loop.run_until_complete(ScraperService.scrape_batch_async(urls))
