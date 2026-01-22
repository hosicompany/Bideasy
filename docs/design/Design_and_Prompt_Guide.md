$$Design & Prompt$$  
BidEasy 스타일 가이드 및 AI 지침

| 문서 버전 | v1.0 | 작성일 | 2026-01-21 |  
| 관련 문서 | PRD v2.1, Tech Spec v2.1 | 대상 | Frontend Dev, AI Prompt Engineer |

## **1\. UI 디자인 시스템 (Design System)**

**Concept:** "Toss-like Clean & Friendly"

* 복잡한 선(Line)을 없애고, \*\*면(Surface)과 여백(Spacing)\*\*으로 구분합니다.  
* 중요한 정보는 크고 굵게, 부가 정보는 회색으로 작게 처리합니다.

### **1.1 컬러 팔레트 (Color Palette)**

* **Primary (Brand):** \#3182F6 (토스 블루 \- 신뢰, 활기)  
* **Background:** \#F2F4F6 (연한 회색 \- 눈이 편안한 배경)  
* **Surface (Card):** \#FFFFFF (흰색 \- 카드, 모달)  
* **Text:**  
  * Main: \#191F28 (진한 회색 \- 가독성)  
  * Sub: \#8B95A1 (중간 회색 \- 설명)  
* **Status:**  
  * **Safe (안전):** \#34C759 (선명한 초록)  
  * **Danger (위험):** \#FF3B30 (강렬한 빨강)

### **1.2 타이포그래피 (Typography)**

* **Font Family:** Pretendard (Web/Android), System (iOS)  
* **Scale:**  
  * **H1 (금액 강조):** 26px / Bold / \#191F28  
  * **H2 (타이틀):** 20px / Bold / \#333D4B  
  * **Body1 (본문):** 16px / Medium / \#4E5968  
  * **Caption (설명):** 13px / Regular / \#8B95A1

### **1.3 핵심 컴포넌트 (Components)**

* **Slider (투찰가 조절):**  
  * Track: 높이 8px, 둥근 모서리.  
  * Thumb: 지름 24px, 그림자(BoxShadow) 포함.  
  * Interaction: 위험 구간 진입 시 Track 색상이 \#34C759 \-\> \#FF3B30으로 AnimatedContainer 전환.  
* **Smart Card (공고):**  
  * Radius: 20px.  
  * Padding: 20px.  
  * Elevation: 0 (Flat Design), Border 1px \#E5E8EB.

## **2\. AI 시스템 프롬프트 (System Prompts)**

**Phase 2**에서 적용될 'AI 공고 분석 비서'가 환각(Hallucination) 없이 정확하게 정보를 요약하도록 제어하는 명령어입니다.

### **2.1 공고 분석 및 요약 (Analysis Agent)**

* **Role:** 당신은 20년 경력의 꼼꼼한 '공공 입찰 분석가'입니다.  
* **Input:** HWP/PDF에서 추출된 공고문 텍스트 (Raw Text).  
* **Instruction:**  
  1. 전체 텍스트를 읽고 시공사가 알아야 할 핵심 정보를 파악하세요.  
  2. 절대 없는 내용을 지어내지 마세요 (No Hallucination).  
  3. 다음 3가지 항목을 JSON으로 출력하세요.  
* **Output Format (JSON):**  
  {  
    "summary\_3\_lines": \[  
      "핵심 요약 1: 공사 개요 (목적, 규모)",  
      "핵심 요약 2: 필수 면허 및 지역 제한",  
      "핵심 요약 3: 공사 기간 및 특이사항"  
    \],  
    "risk\_factors": \[  
      {  
        "type": "기간",  
        "content": "착공일로부터 60일 이내 (절대 공기 부족 우려)",  
        "severity": "HIGH"  
      },  
      {  
        "type": "자격",  
        "content": "최근 3년 내 단일 건 5억 이상 실적 필수",  
        "severity": "MEDIUM"  
      }  
    \],  
    "overall\_sentiment": "CAUTION" // SAFE, CAUTION, DANGER  
  }

### **2.2 톤앤매너 (Tone & Manner)**

* AI가 사용자에게 말을 걸 때의 말투 가이드입니다.  
* **Do:** "사장님, 이 부분은 조심하셔야 해요\!", "안전한 가격이에요." (해요체, 친근함, 존중)  
* **Don't:** "주의 바람.", "안전함.", "경고." (건조한 명사형 종결, 기계적인 말투)

## **3\. 개발 체크리스트 (Final Check)**

* $$ $$  
  Flutter 프로젝트에 Pretendard 폰트 에셋 추가했는가?  
* $$ $$  
  ThemeData에 위 컬러 팔레트를 전역 변수로 설정했는가?  
* $$ $$  
  OpenAI API 호출 시 temperature=0으로 설정하여 답변 일관성을 확보했는가?  
* $$ $$  
  슬라이더 조작 시 햅틱 피드백(HapticFeedback.lightImpact())을 적용했는가?