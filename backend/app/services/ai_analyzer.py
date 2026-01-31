# -*- coding: utf-8 -*-
"""
AI Document Analyzer - Deep analysis of bid attachments using OpenAI
Analyzes full document text for toxic clauses, qualification requirements, etc.
"""
import json
from typing import Dict, List, Optional
from openai import OpenAI
from app.core.config import settings


class DocumentAnalyzer:
    """
    OpenAI를 사용한 첨부파일 심층 분석
    Long-Context 방식으로 문서 전체 텍스트를 분석
    """

    def __init__(self):
        self.client = OpenAI(api_key=settings.OPENAI_API_KEY)
        self.model = "gpt-5-nano"
        self.fallback_model = "gpt-4o-mini"

    def analyze_attachment(
        self,
        document_text: str,
        bid_info: Optional[Dict] = None
    ) -> Dict:
        """
        첨부파일 텍스트 심층 분석

        Args:
            document_text: 추출된 문서 텍스트
            bid_info: 입찰 공고 기본 정보 (선택)

        Returns:
            분석 결과 딕셔너리
        """
        if not document_text or len(document_text.strip()) < 50:
            return self._empty_result("문서 내용이 너무 짧거나 비어있습니다.")

        system_prompt = self._build_system_prompt()
        user_prompt = self._build_user_prompt(document_text, bid_info)

        try:
            print(f"[AIAnalyzer] 심층 분석 시작 (모델: {self.model})", flush=True)
            print(f"[AIAnalyzer] 문서 길이: {len(document_text)} 문자", flush=True)

            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                response_format={"type": "json_object"},
                temperature=0,
                max_tokens=4096
            )

            result_json = response.choices[0].message.content
            result = json.loads(result_json)

            print(f"[AIAnalyzer] 분석 완료", flush=True)
            return self._validate_result(result)

        except Exception as e:
            print(f"[AIAnalyzer] 기본 모델 실패: {e}", flush=True)

            # Fallback to gpt-4o-mini
            if self.model != self.fallback_model:
                try:
                    print(f"[AIAnalyzer] 폴백 모델 시도: {self.fallback_model}", flush=True)
                    response = self.client.chat.completions.create(
                        model=self.fallback_model,
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt}
                        ],
                        response_format={"type": "json_object"},
                        temperature=0,
                        max_tokens=4096
                    )

                    result_json = response.choices[0].message.content
                    result = json.loads(result_json)
                    return self._validate_result(result)

                except Exception as fallback_e:
                    print(f"[AIAnalyzer] 폴백 모델도 실패: {fallback_e}", flush=True)

            return self._empty_result(f"분석 실패: {str(e)}")

    def _build_system_prompt(self) -> str:
        """시스템 프롬프트 생성"""
        return """당신은 공공 입찰 문서 심층 분석 전문가 AI입니다.
주어진 입찰 첨부문서(규격서, 과업지시서, 계약특수조건 등)를 꼼꼼히 읽고
시공사/입찰자 입장에서 중요한 정보를 추출하세요.

## 분석 항목

1. **qualification_requirements** (자격요건)
   - 필수 면허/자격 (예: 건축공사업, 정보통신공사업 등)
   - 필요 실적 조건 (예: 최근 3년 유사공사 실적)
   - 자본금/신용평가 조건
   - 지역 제한 (예: 본사 소재지 제한)
   - 기술자 보유 조건

2. **toxic_clauses** (독소조항)
   - 과도한 지체상금 (예: 일일 1/1000 이상)
   - 일방적 계약변경 조항
   - 부당한 하자보수 조건 (예: 5년 이상)
   - 과도한 보험/보증 요구
   - 공사비 삭감 조항
   - 부당한 대금지급 조건 (예: 준공 후 6개월)
   - 민원처리 전가 조항

3. **key_conditions** (핵심 조건)
   - 공사/용역 기간
   - 착공일/준공일
   - 대금 지급 조건
   - 보증금 조건
   - 공동도급 조건
   - 하도급 제한
   - 자재 지정 사항

4. **risk_assessment** (위험도 평가)
   - HIGH: 입찰 포기를 고려해야 할 수준
   - MEDIUM: 주의가 필요하나 입찰 가능
   - LOW: 일반적인 수준

5. **summary** (종합 의견)
   - 2-3문장으로 이 문서의 핵심과 주의사항 요약

## 응답 형식 (JSON)
{
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
            "content": "지체상금 일일 계약금액의 3/1000 (통상 1.5/1000 대비 2배)",
            "severity": "HIGH",
            "recommendation": "계약 전 협의 필요"
        }
    ],
    "key_conditions": [
        {
            "category": "공사기간",
            "content": "착공일로부터 180일",
            "note": "동절기 포함시 공기 촉박"
        }
    ],
    "risk_assessment": "MEDIUM",
    "summary": "본 공사는 건축공사업 면허가 필수이며, 지체상금이 통상 대비 높게 책정되어 있어 공기 관리에 주의가 필요합니다."
}

## 주의사항
- 문서에 명시되지 않은 내용은 추측하지 마세요
- 각 항목이 없으면 빈 리스트([])로 반환하세요
- 객관적이고 사실에 기반하여 분석하세요
- 독소조항 판단 시 일반적인 공공계약 기준과 비교하세요"""

    def _build_user_prompt(
        self,
        document_text: str,
        bid_info: Optional[Dict]
    ) -> str:
        """사용자 프롬프트 생성"""
        prompt_parts = []

        if bid_info:
            prompt_parts.append("## 공고 기본 정보")
            prompt_parts.append(f"- 공고명: {bid_info.get('title', 'N/A')}")
            prompt_parts.append(f"- 공고기관: {bid_info.get('organization', 'N/A')}")
            prompt_parts.append(f"- 추정가격: {bid_info.get('estimated_price', 'N/A')}")
            prompt_parts.append("")

        # 텍스트 길이 제한 (토큰 절약)
        max_length = 50000  # 약 12,500 토큰
        if len(document_text) > max_length:
            document_text = document_text[:max_length] + "\n\n[... 문서 일부 생략 ...]"

        prompt_parts.append("## 분석할 첨부문서 내용")
        prompt_parts.append(document_text)
        prompt_parts.append("")
        prompt_parts.append("위 문서를 분석하여 지정된 JSON 형식으로 결과를 제공해주세요.")

        return "\n".join(prompt_parts)

    def _validate_result(self, result: Dict) -> Dict:
        """결과 검증 및 기본값 보정"""
        default_structure = {
            "qualification_requirements": [],
            "toxic_clauses": [],
            "key_conditions": [],
            "risk_assessment": "LOW",
            "summary": ""
        }

        for key, default_val in default_structure.items():
            if key not in result:
                result[key] = default_val

        # risk_assessment 값 검증
        valid_risks = {"HIGH", "MEDIUM", "LOW"}
        if result.get("risk_assessment") not in valid_risks:
            result["risk_assessment"] = "LOW"

        return result

    def _empty_result(self, message: str) -> Dict:
        """빈 결과 반환"""
        return {
            "qualification_requirements": [],
            "toxic_clauses": [],
            "key_conditions": [],
            "risk_assessment": "LOW",
            "summary": "",
            "error": message
        }


# 싱글톤 인스턴스
document_analyzer = DocumentAnalyzer()
