# **\[Tech Spec\] BidEasy v2.2 System Architecture**

| 문서 버전 | v2.2 (Integrated AI & Design) | 작성일 | 2026-01-21 |
| :---- | :---- | :---- | :---- |
| **관련 문서** | PRD v2.1, Style Guide v1.0 | **대상** | AI Developer |

## **1\. 시스템 아키텍처 (System Architecture)**

### **1.1 기술 스택 (Tech Stack)**

* **Frontend:** Flutter (Mobile App)  
  * *State Management:* Riverpod  
  * *Design System:* Custom Widgets based on 'Toss-like' tokens  
* **Backend:** Python FastAPI (Async Server)  
  * *AI Orchestration:* LangChain (Simple Chain for Summarization)  
  * *Task Queue:* Celery \+ Redis (공고 크롤링 및 비동기 AI 분석)  
* **Database:**  
  * *RDBMS:* PostgreSQL (주 데이터 저장)  
  * *Cache:* Redis (피드 캐싱, AI 분석 결과 캐싱)  
* **External APIs:**  
  * *Data:* 공공데이터포털 (입찰공고정보서비스)  
  * *LLM:* OpenAI API (gpt-4o-mini)

### **1.2 디렉토리 구조 (Backend Structure)**

`backend/`  
`├── app/`  
`│   ├── api/v1/             # Endpoints`  
`│   │   ├── endpoints/`  
`│   │   │   ├── bids.py     # 공고 조회 및 계산`  
`│   │   │   └── ai.py       # [New] AI 분석`  
`│   ├── core/               # Config & Security`  
`│   ├── db/                 # Models & CRUD`  
`│   ├── services/`  
`│   │   ├── calculator.py   # 안전 계산 로직 (Core)`  
`│   │   ├── crawler.py      # 공고 데이터 수집`  
`│   │   └── llm_agent.py    # [New] 공고 요약/분석 에이전트`  
`│   └── schemas/            # Pydantic Models`  
`└── main.py`

## **2\. 데이터베이스 설계 (Database Schema)**

### **2.1 주요 테이블 (Core Tables)**

*(Users, Notices, User\_Bids는 v1.0과 동일, 생략)*

### **2.2 \[New\] AI\_Analysis\_Logs (AI 분석 캐시)**

*비싼 LLM API 호출 횟수를 줄이기 위해 분석 결과를 영구 캐싱*

| Field | Type | Description |
| :---- | :---- | :---- |
| bid\_no | VARCHAR(PK) | 공고번호 (Foreign Key to Notices) |
| summary\_json | JSONB | 3줄 요약 및 핵심 정보 |
| risk\_factors | JSONB | 독소조항 리스트 (Severity 포함) |
| llm\_model | VARCHAR | 사용 모델 (예: gpt-4o-mini) |
| token\_usage | INTEGER | 사용된 토큰 수 (비용 추적용) |
| created\_at | TIMESTAMP | 분석 생성 시점 |

## **3\. API 명세 (API Specification)**

### **3.1 Smart Feed & Calculator**

* GET /api/v1/feed: 맞춤 공고 피드 조회.  
* POST /api/v1/bids/calculate: 투찰가 계산 및 안전성 검증.

### **3.2 \[New\] AI Analysis API**

* **Endpoint:** GET /api/v1/bids/{bid\_no}/analysis  
* **Description:** 공고 상세 텍스트를 AI로 분석하여 요약과 위험 요소를 반환.  
* **Process Flow:**  
  1. DB(AI\_Analysis\_Logs) 조회.  
  2. **Cache Hit:** 저장된 JSON 반환 (비용 0원).  
  3. **Cache Miss:**  
     * 공고 원문(HTML/Text) 파싱.  
     * LLM API 호출 (System Prompt 적용).  
     * 결과 DB 저장 및 반환.  
* **Response Example:**  
  `{`  
    `"summary": {`  
      `"overview": "강남구 구민회관 리모델링 공사",`  
      `"requirements": "실내건축공사업 면허 필수",`  
      `"schedule": "착공일로부터 90일"`  
    `},`  
    `"risks": [`  
      `{`  
        `"type": "기간",`  
        `"content": "공사 기간이 촉박함 (절대 공기 부족 우려)",`  
        `"level": "HIGH"`  
      `}`  
    `]`  
  `}`

## **4\. 핵심 로직 및 알고리즘 (Core Logic)**

### **4.1 투찰가 안전성 검사 (Safety Calculator)**

* **Rule:** 낙찰하한율 미만 투찰 시 무조건 DANGER 리턴.  
* **Precision:** math.floor(price / 10\) \* 10 (1원 단위 절사 필수).

### **4.2 \[New\] AI Prompt Engineering (LLM Agent)**

* **System Prompt:**  
  `당신은 공사 입찰 전문 분석가입니다. 주어진 공고문을 읽고 다음 JSON 스키마에 맞춰 답변하세요.`  
  `- summary: 핵심 내용 3줄 요약.`  
  `- risks: 시공사 입장에서 불리한 독소조항(기간, 페널티, 특수자격) 추출.`  
  `- tone: 객관적이고 건조하게(Dry) 사실만 전달.`

## **5\. 프론트엔드 구현 요구사항 (Frontend Requirements)**

### **5.1 디자인 토큰 (Design Tokens)**

*디자인 가이드를 코드로 변환*

* **Fonts:** Pretendard (Default).  
* **Colors:**  
  * primaryBlue: Color(0xFF3182F6)  
  * backgroundGrey: Color(0xFFF2F4F6)  
  * safeGreen: Color(0xFF34C759)  
  * dangerRed: Color(0xFFFF3B30)

### **5.2 인터랙션 (Interaction)**

* **Slider Haptics:** 슬라이더 값이 변경될 때마다 HapticFeedback.selectionClick() 호출.  
* **Safety Alert:** 안전 구간 이탈 시 슬라이더 트랙 색상이 AnimatedContainer로 부드럽게(Duration: 300ms) 전환.

## **6\. 보안 및 최적화 (Security & Optimization)**

* **Rate Limiting:** AI 분석 API는 유저당 일일 5회(무료) 또는 무제한(유료) 제한 적용.  
* **Data Encryption:** 사용자의 사업자번호 등 민감 정보는 AES-256 암호화 저장.