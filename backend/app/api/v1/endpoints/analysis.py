# -*- coding: utf-8 -*-
"""
Deep Analysis API Endpoint
Analyzes bid attachments (HWP, PDF) for toxic clauses, qualifications, etc.
"""
import os
import tempfile
from fastapi import APIRouter, Depends, Query

import httpx

from app.services.bid_detail import BidDetailService
from app.services.document_parser import DocumentParser
from app.services.ai_analyzer import document_analyzer
from app.schemas.analysis import DeepAnalysisResponse
from app.core.logging import get_logger
from app.core.security import require_tier

logger = get_logger(__name__)

router = APIRouter()


class AttachmentDownloader:
    """첨부파일 다운로드 서비스"""

    # 나라장터 첨부파일 API (공개정보)
    ATTACHMENT_API_URL = "https://apis.data.go.kr/1230000/PubDataOpnStdService/getDataSetOpnStdBidPblancAtchFileInfo"

    @staticmethod
    async def get_attachment_list(bid_ntce_no: str, api_key: str) -> list:
        """
        입찰 공고의 첨부파일 목록 조회
        1. 상세 정보 API (BidDetail)에서 ntceSpecDocUrl 확인
        2. 없으면 첨부파일 API 시도 (Fallback)
        """
        attachments = []
        
        # 1. Try Bid Detail First (Reliable for ntceSpecDocUrl)
        try:
            # bid_ntce_no format: R25BK...-000 -> split to ID and Ord
            if "-" in bid_ntce_no:
                bid_no_only, bid_ord = bid_ntce_no.split("-")
            else:
                bid_no_only, bid_ord = bid_ntce_no, "00"
                
            logger.info(f"Checking BidDetail for {bid_no_only}-{bid_ord}...")
            # Use the new robust method
            detail = BidDetailService.fetch_bid_detail_robust(bid_no_only, bid_ord)
            
            if detail and "raw_data" in detail:
                 item = detail["raw_data"]
                 for i in range(1, 11):
                     url_key = f"ntceSpecDocUrl{i}"
                     name_key = f"ntceSpecFileNm{i}"
                     
                     url = item.get(url_key)
                     name = item.get(name_key)
                     
                     if url and name:
                         attachments.append({
                             "atchFileNm": name,
                             "atchFileUrl": url
                         })
        except Exception as e:
             logger.error(f"BidDetail Error: {e}")

        if attachments:
            logger.info(f"Found {len(attachments)} files via BidDetail.")
            return attachments
            
        # 2. Fallback to Attachment API
        logger.info(f"Fallback to Attachment API for {bid_ntce_no}...")
        params = {
            "serviceKey": api_key,
            "numOfRows": 100,
            "pageNo": 1,
            "type": "json",
            "bidNtceNo": bid_ntce_no,
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    AttachmentDownloader.ATTACHMENT_API_URL,
                    params=params
                )

                if response.status_code != 200:
                    logger.error(f"HTTP Error: {response.status_code}")
                    return []

                data = response.json()
                body = data.get("response", {}).get("body", {})
                items = body.get("items", [])

                if isinstance(items, dict):
                    items = [items]

                return items if items else []

        except Exception as e:
            logger.error(f"API Error: {e}")
            return []

    @staticmethod
    async def download_file(url: str, save_path: str) -> bool:
        """
        URL에서 파일 다운로드

        Args:
            url: 다운로드 URL
            save_path: 저장 경로

        Returns:
            성공 여부
        """
        try:
            async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
                response = await client.get(url)

                if response.status_code == 200:
                    with open(save_path, "wb") as f:
                        f.write(response.content)
                    return True
                else:
                    logger.error(f"Download failed: {response.status_code}")
                    return False

        except Exception as e:
            logger.error(f"Download error: {e}")
            return False


@router.post("/{bid_id}/deep", response_model=DeepAnalysisResponse)
async def deep_analyze_bid(
    bid_id: str,
    include_raw_text: bool = Query(
        default=False,
        description="추출된 원문 텍스트 포함 여부"
    ),
    _user=Depends(require_tier("pro")),
) -> DeepAnalysisResponse:
    """
    입찰 공고 첨부파일 심층 분석

    HWP, PDF 형식의 첨부파일을 다운로드하여 텍스트 추출 후
    AI를 사용해 독소조항, 자격요건 등을 분석합니다.

    Args:
        bid_id: 입찰 공고 번호 (예: R25BK01250181)
        include_raw_text: 추출된 원문 포함 여부

    Returns:
        DeepAnalysisResponse: 심층 분석 결과
    """
    from app.core.config import settings

    logger.info(f"심층 분석 시작: {bid_id}")

    # 1. 입찰 공고 정보 조회
    bid_detail = BidDetailService.fetch_bid_detail(bid_id)
    bid_title = bid_detail.get("title") if bid_detail else None

    if not bid_detail:
        logger.warning(f"공고 정보 조회 실패: {bid_id}")
        # 공고 정보 없이도 첨부파일 분석 시도

    # 2. 첨부파일 목록 조회
    attachments = await AttachmentDownloader.get_attachment_list(
        bid_id,
        settings.PUBLIC_DATA_KEY
    )

    if not attachments:
        return DeepAnalysisResponse(
            bid_id=bid_id,
            bid_title=bid_title,
            error="첨부파일을 찾을 수 없습니다."
        )

    logger.info(f"첨부파일 {len(attachments)}개 발견")

    # 3. 지원 형식의 첨부파일 필터링 및 다운로드
    all_text_parts = []
    analyzed_files = []

    with tempfile.TemporaryDirectory() as temp_dir:
        for attach in attachments:
            file_name = attach.get("atchFileNm", "")
            file_url = attach.get("atchFileUrl", "")

            if not file_name or not file_url:
                continue

            # 확장자 확인
            ext = os.path.splitext(file_name)[1].lower()
            if ext not in {".hwp", ".hwpx", ".pdf"}:
                logger.info(f"지원하지 않는 형식 스킵: {file_name}")
                continue

            # 파일 다운로드
            save_path = os.path.join(temp_dir, file_name)
            logger.info(f"다운로드 중: {file_name}")

            success = await AttachmentDownloader.download_file(file_url, save_path)
            if not success:
                logger.error(f"다운로드 실패: {file_name}")
                continue

            # 텍스트 추출
            logger.info(f"텍스트 추출 중: {file_name}")
            text = DocumentParser.extract_text(save_path)

            if text and len(text.strip()) > 100:
                all_text_parts.append(f"=== {file_name} ===\n{text}")
                analyzed_files.append(file_name)
                logger.info(f"추출 완료: {len(text)} 문자")
            else:
                logger.warning(f"추출된 텍스트 없음: {file_name}")

    if not all_text_parts:
        return DeepAnalysisResponse(
            bid_id=bid_id,
            bid_title=bid_title,
            analyzed_files=[],
            error="첨부파일에서 텍스트를 추출할 수 없습니다."
        )

    # 4. 전체 텍스트 병합
    combined_text = "\n\n".join(all_text_parts)
    logger.info(f"전체 텍스트: {len(combined_text)} 문자")

    # 5. AI 분석
    bid_info = {
        "title": bid_title or bid_id,
        "organization": bid_detail.get("organization") if bid_detail else None,
        "estimated_price": bid_detail.get("estimated_price") if bid_detail else None,
    }

    analysis_result = document_analyzer.analyze_attachment(
        document_text=combined_text,
        bid_info=bid_info
    )

    # 6. 응답 생성
    response = DeepAnalysisResponse(
        bid_id=bid_id,
        bid_title=bid_title,
        qualification_requirements=analysis_result.get("qualification_requirements", []),
        toxic_clauses=analysis_result.get("toxic_clauses", []),
        key_conditions=analysis_result.get("key_conditions", []),
        risk_assessment=analysis_result.get("risk_assessment", "LOW"),
        summary=analysis_result.get("summary", ""),
        analyzed_files=analyzed_files,
        error=analysis_result.get("error")
    )

    logger.info(f"완료: 위험도 {response.risk_assessment}")
    return response


@router.get("/{bid_id}/attachments")
async def list_attachments(bid_id: str):
    """
    입찰 공고 첨부파일 목록 조회

    Args:
        bid_id: 입찰 공고 번호

    Returns:
        첨부파일 목록
    """
    from app.core.config import settings

    attachments = await AttachmentDownloader.get_attachment_list(
        bid_id,
        settings.PUBLIC_DATA_KEY
    )

    return {
        "bid_id": bid_id,
        "total_count": len(attachments),
        "attachments": [
            {
                "file_name": a.get("atchFileNm", ""),
                "file_url": a.get("atchFileUrl", ""),
                "file_size": a.get("atchFileSz", 0),
            }
            for a in attachments
        ]
    }
