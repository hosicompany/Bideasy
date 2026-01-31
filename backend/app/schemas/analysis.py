# -*- coding: utf-8 -*-
"""
Pydantic Schemas for Deep Analysis API
"""
from typing import List, Optional, Literal
from pydantic import BaseModel, Field


class QualificationRequirement(BaseModel):
    """자격요건 항목"""
    category: str = Field(..., description="카테고리 (면허, 실적, 지역 등)")
    content: str = Field(..., description="요건 내용")
    importance: str = Field(default="권장", description="중요도 (필수/권장)")


class ToxicClause(BaseModel):
    """독소조항 항목"""
    type: str = Field(..., description="유형 (지체상금, 하자보수, 대금지급 등)")
    content: str = Field(..., description="조항 내용")
    severity: Literal["HIGH", "MEDIUM", "LOW"] = Field(
        default="MEDIUM",
        description="심각도"
    )
    recommendation: Optional[str] = Field(
        default=None,
        description="권고사항"
    )


class KeyCondition(BaseModel):
    """핵심 조건 항목"""
    category: str = Field(..., description="카테고리 (공사기간, 대금조건 등)")
    content: str = Field(..., description="조건 내용")
    note: Optional[str] = Field(default=None, description="참고사항")


class DeepAnalysisResponse(BaseModel):
    """심층 분석 결과 응답"""
    bid_id: str = Field(..., description="입찰 공고 번호")
    bid_title: Optional[str] = Field(default=None, description="공고명")

    qualification_requirements: List[QualificationRequirement] = Field(
        default_factory=list,
        description="자격요건 목록"
    )
    toxic_clauses: List[ToxicClause] = Field(
        default_factory=list,
        description="독소조항 목록"
    )
    key_conditions: List[KeyCondition] = Field(
        default_factory=list,
        description="핵심 조건 목록"
    )
    risk_assessment: Literal["HIGH", "MEDIUM", "LOW"] = Field(
        default="LOW",
        description="종합 위험도"
    )
    summary: str = Field(default="", description="종합 의견")

    analyzed_files: List[str] = Field(
        default_factory=list,
        description="분석된 첨부파일 목록"
    )

    error: Optional[str] = Field(default=None, description="에러 메시지")

    class Config:
        json_schema_extra = {
            "example": {
                "bid_id": "R25BK01250181",
                "bid_title": "OO구 시설물 보수공사",
                "qualification_requirements": [
                    {
                        "category": "면허",
                        "content": "건축공사업 면허 필수",
                        "importance": "필수"
                    }
                ],
                "toxic_clauses": [
                    {
                        "type": "지체상금",
                        "content": "지체상금 일일 3/1000 (통상 1.5/1000 대비 2배)",
                        "severity": "HIGH",
                        "recommendation": "계약 전 협의 필요"
                    }
                ],
                "key_conditions": [
                    {
                        "category": "공사기간",
                        "content": "착공일로부터 180일",
                        "note": "동절기 포함"
                    }
                ],
                "risk_assessment": "MEDIUM",
                "summary": "지체상금이 높게 책정되어 공기 관리에 주의 필요",
                "analyzed_files": ["규격서.hwp", "계약특수조건.pdf"]
            }
        }


class DeepAnalysisRequest(BaseModel):
    """심층 분석 요청 (선택적 파라미터)"""
    include_raw_text: bool = Field(
        default=False,
        description="추출된 원문 포함 여부"
    )
