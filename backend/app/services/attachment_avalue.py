"""A값 Tier 2 — 첨부문서(공고규격서/산출내역서) 파싱으로 A값 추출.

OpenAPI 엔 A값이 없으므로(판정 C), 공고 첨부 URL(ntceSpecDocUrl)을 받아
다운로드 → DocumentParser(HWP/PDF/HWPX) → ScraperService.extract_a_value
정규식 적용. 익스텐션 보고(Tier 1)가 없어도 서버가 자력으로 A값을 채운다.
best-effort — 문서 양식 편차·다운로드 실패 시 {found:False}.
"""
import os
import re
import tempfile

import requests
import urllib3

from app.services.document_parser import DocumentParser
from app.services.scraper import ScraperService
from app.core.logging import get_logger

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
logger = get_logger(__name__)

_EXT_RE = re.compile(r"\.(hwpx|hwp|pdf|xlsx|xls|docx)", re.IGNORECASE)


class AttachmentAValueExtractor:
    @staticmethod
    def _guess_ext(name: str, url: str) -> str:
        for src in (name or "", url or ""):
            m = _EXT_RE.search(src)
            if m:
                return "." + m.group(1).lower()
        return ".hwp"  # 공고규격서 기본

    @staticmethod
    def extract(attachment_url: str, attachment_name: str = None, timeout: int = 20) -> dict:
        """첨부 다운로드 → 파싱 → A값 추출. {found, total, breakdown} 반환."""
        if not attachment_url:
            return {"found": False}
        ext = AttachmentAValueExtractor._guess_ext(attachment_name, attachment_url)
        path = None
        try:
            resp = requests.get(attachment_url, timeout=timeout, verify=False)
            if resp.status_code != 200 or not resp.content:
                logger.info(f"A값 첨부 다운로드 실패 {resp.status_code}: {attachment_url[:80]}")
                return {"found": False}
            with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as f:
                f.write(resp.content)
                path = f.name
            text = DocumentParser.extract_text(path) or ""
            if not text.strip():
                return {"found": False}
            result = ScraperService.extract_a_value(text)
            if result.get("found"):
                logger.info(f"A값 첨부 추출 성공: {result.get('total')} ({attachment_name})")
            return result
        except Exception as e:
            logger.info(f"A값 첨부 추출 오류: {e}")
            return {"found": False}
        finally:
            if path:
                try:
                    os.remove(path)
                except OSError:
                    pass
