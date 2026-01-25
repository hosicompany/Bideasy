import requests
from bs4 import BeautifulSoup
import re

class ScraperService:
    @staticmethod
    def fetch_page_content(url: str) -> str:
        """
        Fetch HTML from URL and extract relevant text for LLM context.
        Targeting G2B specific structure.
        """
        if not url or not url.startswith("http"):
            return ""

        try:
            # User-Agent is required for some sites
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            }
            
            # 1. Verification Bypass (Optional, G2B sometimes requires SSL verify=False)
            response = requests.get(url, headers=headers, verify=False, timeout=10)
            response.encoding = 'utf-8' # G2B is usually utf-8 or euc-kr
            
            if response.status_code != 200:
                print(f"[Scraper] Failed to fetch {url}: {response.status_code}")
                return ""

            # 2. Parse HTML
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # 3. Extract Core Content (Heuristic)
            # G2B content is usually inside specific divs or tables
            # Strategy: Get all text, but prioritize common container classes
            
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
            # Remove excessive newlines
            cleaned_text = re.sub(r'\n\s*\n', '\n', content_text)
            
            # Limit length for LLM Token limit (e.g. 5000 chars)
            return cleaned_text[:5000]

        except Exception as e:
            print(f"[Scraper] Error scraping {url}: {e}")
            return ""
