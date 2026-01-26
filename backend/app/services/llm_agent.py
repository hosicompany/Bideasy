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
        Analyze notice text and return structured rich data (Badges, Checks, Tips).
        """
        system_prompt = """
        당신은 대한민국 '건설산업기본법'에 능통한 입찰 분석 AI '비드이지'입니다.
        제공된 [실제 공고 본문]을 최우선 근거(Fact)로 하여 분석하세요. 
        
        [주의사항]
        - 예시에 있는 지역(경기도 고양시 등)이나 면허를 그대로 베끼지 마세요. 
        - 반드시 입력된 공고문 텍스트에서 지역과 면허를 찾아서 답하세요.
        - 만약 본문에서 찾을 수 없다면 "분석불가"라고 적으세요.

        [분석 우선순위]
        1. **Fact Check (본문)**: 본문에 명시된 '참가자격', '지역제한', '면허'를 그대로 추출.
        2. **Inference (규칙)**: 본문에 없을 경우 아래 규칙 적용.

        [Output JSON Format 예시 - 형식을 따르되 값은 실제 분석해서 채울것]
        {
            "badges": ["#지역명(Fact)", "#면허명(Fact)"], 
            "check_items": [
                {"status": "WARN", "label": "지역", "text": "실제 공고의 지역명 (본문 명시됨)"},
                {"status": "INFO", "label": "면허", "text": "실제 요구 면허 (추론)"}
            ],
            "tips": ["특이사항이 있다면 요약"]
        }
        """

        try:
            print(f"[LLM] Requesting analysis with model: {self.model}", flush=True)
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
            print(f"[LLM] Primary model ({self.model}) failed: {e}", flush=True)
            
            # Fallback to gpt-4o-mini if using a different model
            if self.model != "gpt-4o-mini":
                try:
                    print(f"[LLM] Retrying with fallback model: gpt-4o-mini", flush=True)
                    response = self.client.chat.completions.create(
                        model="gpt-4o-mini",
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": f"공고문 내용: {notice_text}"}
                        ],
                        response_format={"type": "json_object"},
                        temperature=0 
                    )
                    result_json = response.choices[0].message.content
                    return json.loads(result_json)
                except Exception as fallback_e:
                    print(f"[LLM] Fallback model also failed: {fallback_e}", flush=True)
            
            return {
                "badges": ["#분석실패"],
                "check_items": [{"status": "WARN", "label": "오류", "text": "AI 분석을 불러오지 못했습니다."}],
                "tips": []
            }


llm_agent = LLMAgent()
