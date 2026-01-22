# BidEasy - 개발 가이드

## 프로젝트 개요

**모바일 퍼스트 초간편 입찰 비서** - 공공 입찰 시장에서 데이터 기반의 '관리'와 '분석' 가치를 제공하는 서비스

### 핵심 가치
- **Radical Simplicity**: 복잡한 필터 제거, Zero UI
- **Invisible Safety**: 적자 수주 원천 차단
- **Intellectual Honesty**: 무책임한 낙찰가 예측 배제, AI는 '비서' 역할에 집중

### AI 전략
- **Do**: 공고문 요약, 독소 조항 탐지, 과거 데이터 기반 팩트 분석
- **Don't**: 낙찰가 예측 (사용자 신뢰 보호)

---

## 기술 스택

### Frontend (Flutter)
- **Framework**: Flutter (Cross Platform)
- **State Management**: Riverpod
- **Design System**: Toss-like Clean & Friendly

### Backend (Python)
- **Framework**: FastAPI (Async Server)
- **AI Orchestration**: LangChain
- **Task Queue**: Celery + Redis
- **LLM**: OpenAI API (gpt-4o-mini)

### Database
- **RDBMS**: PostgreSQL (현재 개발: SQLite)
- **Cache**: Redis

### External APIs
- 공공데이터포털 (입찰공고정보서비스)
- OpenAI API

---

## 디렉토리 구조

```
01_Bid Easy/
├── backend/
│   ├── app/
│   │   ├── api/v1/
│   │   │   ├── endpoints/
│   │   │   │   ├── bids.py      # 공고 조회 및 계산
│   │   │   │   └── ai.py        # AI 분석
│   │   │   └── api.py           # 라우터 통합
│   │   ├── core/
│   │   │   └── config.py        # 설정
│   │   ├── db/
│   │   │   ├── base.py          # DB 베이스
│   │   │   ├── models.py        # ORM 모델
│   │   │   └── session.py       # DB 세션
│   │   ├── schemas/
│   │   │   └── bid.py           # Pydantic 스키마
│   │   └── services/
│   │       ├── calculator.py    # 투찰가 계산 로직 (핵심)
│   │       ├── crawler.py       # 공고 데이터 수집
│   │       └── llm_agent.py     # AI 공고 분석 에이전트
│   ├── scripts/
│   │   └── seed_data.py         # 시드 데이터
│   ├── tests/
│   │   └── verify_calc.py       # 계산 로직 검증
│   └── main.py                  # 앱 진입점
├── frontend/
│   └── lib/
│       ├── main.dart            # 앱 진입점
│       ├── models/
│       │   └── notice.dart      # 공고 모델
│       ├── screens/
│       │   └── home_screen.dart # 홈 화면
│       ├── services/
│       │   └── api_service.dart # API 통신
│       ├── theme/
│       │   └── style.dart       # 스타일 정의
│       └── widgets/
│           ├── notice_card.dart # 공고 카드
│           └── bid_slider.dart  # 투찰가 슬라이더
└── docs/                        # 문서
```

---

## API 명세

### 공고 및 계산
| Method | Endpoint | 설명 |
|--------|----------|------|
| GET | `/api/v1/feed` | 맞춤 공고 피드 조회 |
| POST | `/api/v1/bids/calculate` | 투찰가 계산 및 안전성 검증 |

### AI 분석 (Phase 2)
| Method | Endpoint | 설명 |
|--------|----------|------|
| GET | `/api/v1/bids/{bid_no}/analysis` | AI 공고 분석 (요약 + 위험요소) |

**AI 분석 응답 예시:**
```json
{
  "summary": {
    "overview": "강남구 구민회관 리모델링 공사",
    "requirements": "실내건축공사업 면허 필수",
    "schedule": "착공일로부터 90일"
  },
  "risks": [
    {
      "type": "기간",
      "content": "공사 기간이 촉박함 (절대 공기 부족 우려)",
      "level": "HIGH"
    }
  ]
}
```

---

## 핵심 로직

### 투찰가 안전성 검사
- **Rule**: 낙찰하한율 미만 투찰 시 무조건 `DANGER` 리턴
- **Precision**: `math.floor(price / 10) * 10` (1원 단위 절사 필수)

### 슬라이더 범위
- 사정률 조절: **-2% ~ +2%**
- 위험 구간 진입 시 Red Alert 전환 및 복사 버튼 비활성화

---

## 디자인 시스템

### 컬러 팔레트
```dart
// Flutter Colors
const primaryBlue = Color(0xFF3182F6);    // 토스 블루 - 신뢰, 활기
const backgroundGrey = Color(0xFFF2F4F6); // 배경
const surfaceWhite = Color(0xFFFFFFFF);   // 카드, 모달
const textMain = Color(0xFF191F28);       // 메인 텍스트
const textSub = Color(0xFF8B95A1);        // 설명 텍스트
const safeGreen = Color(0xFF34C759);      // 안전
const dangerRed = Color(0xFFFF3B30);      // 위험
```

### 타이포그래피
| 용도 | 크기 | Weight | 색상 |
|------|------|--------|------|
| H1 (금액 강조) | 26px | Bold | #191F28 |
| H2 (타이틀) | 20px | Bold | #333D4B |
| Body1 (본문) | 16px | Medium | #4E5968 |
| Caption (설명) | 13px | Regular | #8B95A1 |

### 폰트
- **Web/Android**: Pretendard
- **iOS**: System Font

### 컴포넌트
- **Slider**: Track 높이 8px, Thumb 지름 24px, 그림자 포함
- **Smart Card**: Radius 20px, Padding 20px, Border 1px #E5E8EB

---

## AI 프롬프트 가이드

### 공고 분석 System Prompt
```
당신은 공사 입찰 전문 분석가입니다. 주어진 공고문을 읽고 다음 JSON 스키마에 맞춰 답변하세요.
- summary: 핵심 내용 3줄 요약.
- risks: 시공사 입장에서 불리한 독소조항(기간, 페널티, 특수자격) 추출.
- tone: 객관적이고 건조하게(Dry) 사실만 전달.
```

### 톤앤매너
- **Do**: "사장님, 이 부분은 조심하셔야 해요!", "안전한 가격이에요." (해요체, 친근함)
- **Don't**: "주의 바람.", "안전함." (건조한 명사형, 기계적)

### AI 분석 출력 포맷
```json
{
  "summary_3_lines": [
    "핵심 요약 1: 공사 개요 (목적, 규모)",
    "핵심 요약 2: 필수 면허 및 지역 제한",
    "핵심 요약 3: 공사 기간 및 특이사항"
  ],
  "risk_factors": [
    {
      "type": "기간",
      "content": "착공일로부터 60일 이내 (절대 공기 부족 우려)",
      "severity": "HIGH"
    }
  ],
  "overall_sentiment": "CAUTION"  // SAFE, CAUTION, DANGER
}
```

---

## 실행 방법

### Backend
```bash
cd backend
pip install -r requirements.txt
python main.py
# 또는 run_backend.bat 실행
```

### Frontend
```bash
cd frontend
flutter pub get
flutter run
# 또는 run_frontend.bat 실행
```

---

## 개발 체크리스트

- [ ] Flutter 프로젝트에 Pretendard 폰트 에셋 추가
- [ ] ThemeData에 컬러 팔레트 전역 변수 설정
- [ ] OpenAI API 호출 시 `temperature=0` 설정 (답변 일관성)
- [ ] 슬라이더 조작 시 햅틱 피드백 적용 (`HapticFeedback.lightImpact()`)

---

## 비즈니스 모델

### Track 1: Basic (건당 500~1,000원)
- 맞춤 공고 피드 + 안전 투찰가 계산기
- 타겟: 월 1~3회 입찰하는 소규모 사업자

### Track 2: AI Premium (월 9,900원)
- Basic + AI 3줄 요약 + 독소조항 자동 탐지
- 타겟: 월 10회 이상 입찰하는 전문 사업자

---

## 보안 및 최적화

- **Rate Limiting**: AI 분석 API는 유저당 일일 5회(무료) / 무제한(유료)
- **Data Encryption**: 사업자번호 등 민감 정보 AES-256 암호화
- **AI 캐싱**: `AI_Analysis_Logs` 테이블에 분석 결과 영구 캐싱 (LLM 비용 절감)
