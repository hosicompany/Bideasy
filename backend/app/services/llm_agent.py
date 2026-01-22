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
        Analyze notice text and return summary and risk factors.
        """
        system_prompt = """
        당신은 공사 입찰 전문 분석가입니다. 주어진 공고문을 읽고 다음 JSON 스키마에 맞춰 답변하세요.
        - summary: 핵심 내용 3줄 요약.
        - risks: 시공사 입장에서 불리한 독소조항(기간, 페널티, 특수자격) 추출.
        - tone: 객관적이고 건조하게(Dry) 사실만 전달.
        
        Output JSON Format:
        {
            "summary": ["Line 1", "Line 2", "Line 3"],
            "risks": [{"type": "Type", "content": "Desc", "level": "HIGH/MEDIUM/LOW"}]
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
                "summary": ["분석 실패", "잠시 후 다시 시도해주세요.", ""],
                "risks": []
            }

llm_agent = LLMAgent()
