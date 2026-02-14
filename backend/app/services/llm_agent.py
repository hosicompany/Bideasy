from openai import OpenAI
import json
from app.core.config import settings


class LLMAgent:
    def __init__(self):
        self.client = OpenAI(api_key=settings.OPENAI_API_KEY)
        self.model = "gpt-4o-mini"
        self.fallback_model = "gpt-4o-mini"

    def analyze_notice(self, notice_text: str) -> dict:
        """
        공고문을 분석하여 3줄 요약 + 위험요소를 반환.
        반환 키: summary (list[str]), risks (list[dict])
        """
        system_prompt = """당신은 건설 공사 입찰 공고를 분석하는 전문가 AI '비드이지'입니다.
주어진 공고문을 읽고 다음 두 가지를 JSON 형식으로 추출하세요.

1. **summary**: 공고의 핵심 내용을 시공사 입장에서 3문장으로 요약.
   - 첫 문장: 공사 개요 (무엇을 하는 공사인지, 규모)
   - 둘째 문장: 핵심 자격 요건 (면허, 실적, 지역)
   - 셋째 문장: 특이사항 (기간, 공동도급, 주의점)
   - 말투: "~함", "~임" 체로 간결하게.

2. **risks**: 시공사에게 불리하거나 주의가 필요한 독소조항/위험요소.
   - 없으면 빈 리스트.
   - type: "기간", "비용", "서류", "처벌", "기타" 중 택1
   - content: 위험 요소의 구체적 내용
   - level: "HIGH" (입찰 포기 고려), "MEDIUM" (주의 필요), "LOW" (참고)

{
    "summary": [
        "서울시 강남구 노후 하수관로 1.5km를 교체하는 30억 규모 공사임.",
        "상하수도설비공사업 면허가 필수이며 서울시 업체만 참여 가능함.",
        "착공 후 60일 이내 완공 조건으로 공기 부족이 우려됨."
    ],
    "risks": [
        {
            "type": "기간",
            "content": "공사 기간 60일로 매우 촉박함 (우천 등 고려 안됨)",
            "level": "HIGH"
        }
    ]
}

주의: 문서에 명시되지 않은 내용은 추측하지 마세요. 객관적 사실만 기술하세요."""

        return self._call_llm(system_prompt, notice_text)

    def _call_llm(self, system_prompt: str, notice_text: str) -> dict:
        """LLM 호출 (폴백 포함)"""
        # 컨텍스트 제한 (약 2500 토큰)
        max_chars = 10000
        truncated = notice_text[:max_chars]
        if len(notice_text) > max_chars:
            truncated += "\n\n[... 이하 생략 ...]"

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"공고문 내용:\n{truncated}"},
        ]

        for model in [self.model, self.fallback_model]:
            try:
                print(f"[LLM] Requesting analysis with model: {model}", flush=True)
                response = self.client.chat.completions.create(
                    model=model,
                    messages=messages,
                    response_format={"type": "json_object"},
                    temperature=0,
                )
                result = json.loads(response.choices[0].message.content)

                # 키 정규화 (이전 프롬프트 호환)
                if "summary_3_lines" in result and "summary" not in result:
                    result["summary"] = result.pop("summary_3_lines")
                if "risk_factors" in result and "risks" not in result:
                    result["risks"] = result.pop("risk_factors")

                return result
            except Exception as e:
                print(f"[LLM] Model {model} failed: {e}", flush=True)

        return {"summary": [], "risks": []}


llm_agent = LLMAgent()
