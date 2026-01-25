from openai import OpenAI
import json
from app.core.config import settings

class LLMAgent:
    def __init__(self):
        # Initialize OpenAI Client
        # Note: Requires OPENAI_API_KEY in .env
        self.client = OpenAI(api_key=settings.OPENAI_API_KEY)
        self.model = "gpt-4o-mini"

    def analyze_notice(self, notice_text: str) -> dict:
        """
        Analyze notice text and return structured rich data (Badges, Checks, Tips).
        """
        system_prompt = """
        당신은 대한민국 '건설산업기본법'에 능통한 입찰 분석 AI '비드이지'입니다.
        제공된 [실제 공고 본문]을 최우선 근거(Fact)로 하여 분석하세요. 본문에 내용이 없을 경우에만 주어칙 규칙으로 추론(Inference)하세요.

        [분석 우선순위]
        1. **Fact Check (본문)**: 본문에 명시된 '참가자격', '지역제한', '면허'를 그대로 추출.
        2. **Inference (규칙)**: 본문에 없을 경우 아래 규칙 적용.

        [법령 및 추론 규칙 (Fallback)]
        1. **면허 추론**: 금액 1.5억 미만(전문), 4억 미만(상호시장), 키워드 기반(실내/전기/통신).
        2. **지역 제한**: 100억 미만(종합)/10억 미만(전문)/5억 미만(보통 시군구 제한).
        3. **계약**: 2천만원 이하(1인수의).

        [Output JSON Format]
        {
            "badges": ["#태그1", "#태그2"], 
            // 예: #경기_고양(Fact), #면허필수(Fact), #전국가능(Fact)
            
            "check_items": [
                {"status": "WARN", "label": "지역", "text": "경기도 고양시 (본문 명시됨)"},
                {"status": "INFO", "label": "면허", "text": "실내건축공사업 (추론)"}
            ],
            "tips": ["공고문에 현장설명회 의무 참석 문구가 있습니다.(Fact)"]
        }
        """

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"공고문 내용: {notice_text}"}
                ],
                response_format={"type": "json_object"},
                temperature=0 
            )
            
            result_json = response.choices[0].message.content
            return json.loads(result_json)
        except Exception as e:
            print(f"LLM Analysis Failed: {e}")
            return {
                "badges": ["#분석실패"],
                "check_items": [{"status": "WARN", "label": "오류", "text": "AI 분석을 불러오지 못했습니다."}],
                "tips": []
            }


llm_agent = LLMAgent()
