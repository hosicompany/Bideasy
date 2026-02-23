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

### AI 분석
| Method | Endpoint | 설명 |
|--------|----------|------|
| GET | `/api/v1/ai/{bid_no}/analysis` | AI 공고 분석 (요약 + 위험요소) |

### 첨부파일 분석
| Method | Endpoint | 설명 |
|--------|----------|------|
| POST | `/api/v1/analysis/{bid_id}/deep` | 첨부파일 심층 분석 (독소조항 탐지) |
| GET | `/api/v1/analysis/{bid_id}/attachments` | 첨부파일 목록 조회 |

### 기관 프로파일링
| Method | Endpoint | 설명 |
|--------|----------|------|
| POST | `/api/v1/agency/profile` | 기관 프로파일 분석 (인증 필요) |
| GET | `/api/v1/smart-bid/agency/search` | 기관명 검색 |
| GET | `/api/v1/smart-bid/agency/insights` | 기관 입찰 인사이트 |
| GET | `/api/v1/smart-bid/agency/stats` | 기관 통계 |

### 스마트 입찰 (ML)
| Method | Endpoint | 설명 |
|--------|----------|------|
| POST | `/api/v1/smart-bid/competition/predict` | 경쟁 강도 예측 |
| POST | `/api/v1/smart-bid/recommend` | 스마트 투찰 추천 |
| POST | `/api/v1/smart-bid/rate/predict` | 사정률 예측 |
| POST | `/api/v1/smart-bid/verify` | 투찰가 검증 |
| GET | `/api/v1/prediction/{bid_no}/recommend-points` | 과학적 분석 추천 포인트 |

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
- [x] 슬라이더 조작 시 햅틱 피드백 적용 (`HapticFeedback.lightImpact()`)
- [x] 위험 구간 진입/탈출 시 강한 햅틱 피드백 (`HapticFeedback.heavyImpact()`)
- [x] 즐겨찾기 토글 시 햅틱 피드백 적용
- [x] 로딩/에러/빈 상태 UI 공통 위젯 구현 (`widgets/state_widgets.dart`)
- [x] 스낵바 유틸리티 구현 (`utils/snackbar_utils.dart`)
- [x] Pull-to-refresh 적용
- [x] MyPageScreen 리디자인 (토스 스타일)
- [x] 프로필 헤더 (포인트, 시공능력 표시)
- [x] 앱 정보 섹션 (버전, 이용약관, 로그아웃)

---

## 비즈니스 모델

### 포지셔닝
- **브랜드**: "입찰 안전 비서" — 잃지 않게 지켜주는 비서
- **슬로건**: "입찰, 지는 게임은 안 합니다"
- **GTM**: 기존 입찰정보 서비스의 "보완재"로 진입 → 독립 확장

### 가격 구조 (3-Tier SaaS)

| | Free | Pro | Pro+ |
|---|---|---|---|
| **월 가격** | 무료 | 14,900원 | 29,900원 |
| **연간 가격** | — | 12,400원/월 (2개월 무료) | 24,900원/월 (2개월 무료) |
| 공고 피드 | ✅ | ✅ | ✅ |
| 투찰가 계산기 | ✅ | ✅ | ✅ |
| AI 분석 | 일 1회 | 무제한 | 무제한 |
| Deep Analysis (첨부파일) | ❌ | ✅ | ✅ |
| 경쟁 강도 예측 | ❌ | ✅ | ✅ |
| 투찰가 검증 | ❌ | ✅ | ✅ |
| 기관 프로파일링 | ❌ | ❌ | ✅ |
| 스마트 추천 | ❌ | ❌ | ✅ |
| 사정률 예측 | ❌ | ❌ | ✅ |

### Tier 상수 (코드)
```python
# backend/app/schemas/subscription.py
TIER_FREE = "free"
TIER_PRO = "pro"
TIER_PRO_PLUS = "pro_plus"

SIGNUP_BONUS = 3000          # 가입 보너스 포인트
FREE_AI_DAILY_LIMIT = 1      # Free 티어 AI 분석 일일 한도
```

### Unit Economics
- OpenAI API 비용: ~2,000~3,000원/유저/월 (gpt-4o-mini)
- Pro 마진: ~60~80%
- 12개월 MRR 목표: 180만~2,500만원 (유료 전환율 3~5%)

---

## 보안 및 최적화

- **Rate Limiting**: AI 분석 — Free 일 1회 / Pro·Pro+ 무제한
- **Feature Gating**: Deep Analysis, 경쟁 예측, 기관 프로파일링은 티어별 접근 제한
- **Data Encryption**: 사업자번호 등 민감 정보 AES-256 암호화
- **AI 캐싱**: `AI_Analysis_Logs` 테이블에 분석 결과 영구 캐싱 (LLM 비용 절감)
