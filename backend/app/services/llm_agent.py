from openai import OpenAI
import json
from app.core.config import settings

class LLMAgent:
    def __init__(self):
        # Initialize OpenAI Client
        # Note: Requires OPENAI_API_KEY in .env
        self.client = OpenAI(api_key=settings.OPENAI_API_KEY)
        self.model = "gpt-5-nano"

    def analyze_notice(self, notice_text: str) -> dict:
        """
        Analyze notice text and return structured rich data (Summary, Risks).
        """
        system_prompt = """
        당신은 건설 공사 입찰 공고를 분석하는 전문가 AI '비드이지'입니다.
        주어진 [공고문 본문]을 읽고 다음 두 가지를 JSON 형식으로 추출하세요.

        1. **summary_3_lines**: 공고의 핵심 내용을 시공사 입장에서 가장 중요한 순서대로 3문장으로 요약.
           - 첫 문장: 공사 개요 (무엇을 하는 공사인지, 규모 등)
           - 둘째 문장: 핵심 자격 요건 (면허, 실적, 지역 등)
           - 셋째 문장: 특이사항 (기간, 공동도급 여부, 기타 주의점)
           - 말투: "~함", "~임" 체로 간결하게.

        2. **risk_factors**: 시공사에게 불리하거나 주의가 필요한 '독소조항' 또는 '위험요소'.
           - 없으면 빈 리스트.
           - type: 기간, 비용, 서류, 처벌, 기타 중 택1
           - content: 위험 요소의 구체적 내용
           - severity: HIGH (입찰 포기 고려), MEDIUM (주의 필요)

        [Response JSON Format]
        {
            "summary_3_lines": [
                "서울시 강남구 노후 하수관로 1.5km를 교체하는 30억 규모 공사임.",
                "상하수도설비공사업 면허가 필수이며 서울시 업체만 참여 가능함.",
                "착공 후 60일 이내 완공 조건으로 절대 공기 부족이 우려됨."
            ],
            "risk_factors": [
                {
                    "type": "기간",
                    "content": "공사 기간 60일로 매우 촉박함 (우천 등 고려 안됨)",
                    "severity": "HIGH"
                }
            ]
        }
        """

        try:
            print(f"[LLM] Requesting analysis with model: {self.model}", flush=True)
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"공고문 내용: {notice_text[:3000]}"} # Limit context to save tokens/cost
                ],
                response_format={"type": "json_object"},
                temperature=0 
            )
            
            result_json = response.choices[0].message.content
            return json.loads(result_json)
            
        except Exception as e:
            print(f"[LLM] Primary model ({self.model}) failed: {e}", flush=True)
            
            # Fallback to gpt-4o-mini if using a different model
            if self.model != "gpt-4o-mini":
                try:
                    print(f"[LLM] Retrying with fallback model: gpt-4o-mini", flush=True)
                    response = self.client.chat.completions.create(
                        model="gpt-4o-mini",
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": f"공고문 내용: {notice_text[:3000]}"}
                        ],
                        response_format={"type": "json_object"},
                        temperature=0 
                    )
                    result_json = response.choices[0].message.content
                    return json.loads(result_json)
                except Exception as fallback_e:
                    print(f"[LLM] Fallback model also failed: {fallback_e}", flush=True)
            
            # Final Fallback
            return {
                "summary_3_lines": [],
                "risk_factors": []
            }


llm_agent = LLMAgent()
