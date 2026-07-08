# 리드 확보 전략 & 구현 — 무료 자격 진단

> 최종 갱신: 2026-07-08 · 상태: **Phase 1(웹 캡처) 구현 완료·미배포** / Phase 2(육성·익스텐션) 설계
> 정본: 이 문서. 전략 상위 맥락 = 메모리 `bideasy-gtm-strategy`, 콘텐츠 채널 = `bideasy-content-strategy`.

---

## 0. 결론 먼저

- **문제**: 랜딩 *전환 구조*(방문→계산기/익스텐션→14일 체험)는 갖췄지만, **아직 안 살 방문자를 붙잡는 리드 캡처가 0**이었다. 신중한 40~60대 시공사 대표는 첫 방문에 카드 없는 체험조차 부담 → 이탈 후 재접촉 경로 없음.
- **해법**: **무료 자격 진단** 리드 마그넷. "우리 회사가 지금 넣을 수 있는 공고, 30초 확인." 업종·지역 입력 → 자격 PASS 공고만 필터 → 매칭 수·상위 3건 즉시 노출 → 전체 목록·알림은 연락처로 잠금해제.
- **왜 이것인가** (전략 정합):
  1. **훅과 정확히 일치** — 발견된 pain(가격보다 자격필터가 먼저·자주, n=1)을 그대로 무료 도구화.
  2. **리드 + 검증 데이터 동시 수집** — 진단 입력(업종·지역)이 곧 비치헤드 검증 마이크로설문.
  3. **기존 자산 재사용** — `QualificationChecker`(단일소스) + 공고 DB. 신규 엔진 0.
  4. **제품으로 자연 연결** — 결과 → "나라장터에서 바로 보려면 익스텐션" → 체험.
- **제약**: 발송 인프라(SES/알림톡) 미구축 → **캡처는 지금 라이브 가능, 육성 발송은 Phase 2.** Phase 1은 발송 의존 없이 즉시 온페이지 가치 + 연락처 저장까지만.

---

## 1. 퍼널 구조

```
[유입: 랜딩 CTA·검색광고·오가닉·블로그]
        │  (가입 없이)
        ▼
① 진단  POST /leads/diagnose      ← 비로그인·연락처 0. 매칭 수 + 상위 3건 미리보기
        │
        ▼
② 캡처  POST /leads/capture       ← 연락처(이메일/휴대폰) → Lead 저장 + 전체 목록 잠금해제
        │
        ▼
③ 육성  (Phase 2)                 ← nurture_channel(kakao 알림톡 / email SES) 병행 발송
        │
        ▼
④ 전환  가입(14일 체험) / 익스텐션 설치 → Lead.converted_user_id 연결
```

**측정 KPI** (낙찰률 금지 — 전역 규칙): 진단 완료율 · 진단→캡처 전환율 · 캡처→가입 전환율 · 채널별 리드→유료.

---

## 2. Phase 1 — 구현 완료(미배포)

### 백엔드
| 항목 | 위치 |
|---|---|
| `Lead` 모델 | `backend/app/db/models.py` (연락처·업종/면허·지역·시공능력·matched_count·UTM·nurture_channel/status·converted_user_id·source) |
| 마이그레이션 | `backend/alembic/versions/d9f3a1b7c204_add_leads_table.py` (head `c4f8a1e7d602` 위, 추가 전용) |
| 엔드포인트 | `backend/app/api/v1/endpoints/leads.py` → `POST /leads/diagnose`·`POST /leads/capture` (공개·IP 레이트리밋) |
| 라우터 등록 | `backend/app/api/v1/api.py` (`prefix="/leads"`) |
| 테스트 | `backend/tests/test_leads.py` (8건) — 전체 313 pass |

**매칭 로직**: 로그인 없이 동작하도록 `QualificationChecker.check_qualification()`에 가상 프로필(`SimpleNamespace(location, licenses)`)을 주입. 업종 루트 키워드(전기/정보통신/소방/건축/토목)로 후보 공고를 공종 필터 → 활성(마감 전) 공고를 지역·면허 판정 → PASS만 반환(스캔 상한 500, 반환 상한 50, 미리보기 3).

> ⚠️ 현재 `QualificationChecker`는 **공고 제목 키워드**로 면허를 추정한다(구조화 필드 부재). 지역은 `Notice.region` 부분일치. 정밀도 한계가 있으나 리드 마그넷 미리보기 용도로 충분. 정밀화는 첨부 파싱·구조화 자격필드 축적 후(로드맵 §5).

### 웹
| 항목 | 위치 |
|---|---|
| 진단 페이지 | `infra/nginx/html/diagnose.html` → 클린 URL `/diagnose` (nginx `try_files $uri.html` 자동 서빙, 설정 변경 불필요) |
| 랜딩 진입점 | `infra/nginx/html/index.html` hero — "가입 없이 → …30초 진단" 링크(`data-ev="cta_hero_diagnose"`) |
| 3스텝 폼 | ① 업종 칩(면허 루트) ② 지역 시·도 ③ 시공능력(선택) → 결과(매칭 수 + top3, 나머지 blur) → 연락처 캡처 → 전체 공개 + 다음 CTA |
| 공통 헬퍼 | `window.BD.esc`(XSS), `won`, `mountNav`, `API_BASE` 재사용. UTM은 `localStorage.bd_attr`(first-touch) → capture로 전송 |

### 배포 (미실행)
```bash
cd ~/Bideasy/infra && ./deploy.sh deploy   # 마이그레이션 자동(alembic upgrade head) — leads 테이블 생성
```
- 정적 웹(`diagnose.html`·`index.html`)은 nginx 볼륨 반영. 익스텐션 재심사 불필요(웹 전용).
- 배포 후 GA4에서 `cta_hero_diagnose`·`lead_diagnose`·`lead_capture` 유입 관찰.

---

## 3. Phase 2 — 육성(nurture) 아키텍처 (설계)

**목표**: 카카오 알림톡 + 이메일(SES)을 **둘 다 꽂히는 pluggable 구조**로. `Lead.nurture_channel`(kakao|email) + `nurture_status`(new→queued→sent→converted→unsub)로 채널·상태를 행마다 관리.

### 채널 분기 (권장 설계)
```
Lead.nurture_channel
├── "kakao"  → 카카오 알림톡 (휴대폰 남긴 리드)   ★ 도달률↑, 40~60대 대표 선호
│              템플릿 사전 심사 필요(영업일 며칠). 발신프로필·템플릿 승인 후 API.
└── "email" → AWS SES (이메일 남긴 리드)          도메인(DKIM/SPF) 인증 + 발신 승인 필요
```
- 공통 인터페이스 `services/nurture.py`(신설 예정): `send(lead, template, ctx)` → 채널별 어댑터(`kakao_alimtalk.py`/`ses_mailer.py`)로 위임. 결제 PG 다중화(`payple.py`/`billing.py`)와 동일한 pluggable 패턴.
- **Celery 스케줄**(신설): 예) 매일 07:30 `nurture.send_new_notice_matches` — 각 리드의 조건에 새로 뜬 공고를 채널별 발송. 첫 진단 직후 즉시 1통(웰컴 + 매칭 요약)도 후보.
- **수신거부**: `nurture_status="unsub"` + 알림톡/메일 하단 opt-out 링크(법적 필수). 링크 = 서명 토큰(로그인 불요).

### 지금 안 하는 이유·순서
- SES·알림톡 모두 **외부 승인 리드타임**(도메인 인증/템플릿 심사)이 있어 코드보다 신청이 먼저. Phase 1 배포로 **리드가 쌓이기 시작하면** 병행 신청 → 승인 나는 대로 발송 어댑터 연결.
- 그전까지 캡처된 리드는 **인앱/수동**으로 접촉 가능(수는 적을 것이므로 초기엔 수동도 유효 — founder 저비용 원칙).

---

## 4. 익스텐션 오버레이 진단 CTA (설계 — 별도 레포 `Bideasy-Extension/`)

익스텐션은 나라장터 화면 위 오버레이 = **최상단 워크플로 접점**. 리드 관점의 역할:

1. **비로그인 오버레이 → 진단·가입 유도**: 로그인 안 한 사용자가 공고를 열면, 오버레이에 "이 공고, 우리 회사가 넣을 수 있나? 무료 자격 진단" CTA → `bideasy.kr/diagnose?utm_source=extension&utm_medium=overlay`로 이동(현재 보고 있는 공고의 공종·지역을 쿼리로 프리필 가능).
2. **A값 크라우드소스 기여자 = 잠재 리드**: 익스텐션이 A값을 보고하는 사용자는 이미 활성 투찰자 → 계정 유도 우선순위.
3. **자격 뱃지 → 캡처**: 오버레이의 자격 PASS/FAIL 뱃지 옆 "맞는 공고 더 받기" → 캡처.

**구현 유의**: 익스텐션 코드 변경은 **Chrome 웹스토어 재심사** 유발(승인 며칠). 그래서 이번 세션 범위에서 **제외**(설계만). 재제출 대기 항목(`plan→tier` 정리·포인트 버튼·툴바 아이콘 빌드)과 **묶어서 한 번에** 반영하는 게 심사 비용상 유리. → CLAUDE.md §1 "익스텐션 재제출" 참조.

---

## 5. 측정 & 데이터

- **유입 귀속**: `localStorage.bd_attr`(first-touch UTM, `app.js`) → capture 시 `Lead.utm_*`에 저장. users의 `signup_source` 스키마와 동형 → 리드·가입을 **같은 채널 축**으로 비교 가능.
- **GA4 이벤트**: `cta_hero_diagnose`(랜딩 클릭) · `lead_diagnose`(진단 실행, industry 파라미터) · `lead_capture`(캡처 성공, channel·matched) · `cta_diagnose_trial`·`cta_diagnose_install`(결과 후 CTA).
- **admin 집계**(로드맵): 기존 `GET /admin/stats/attribution` 패턴을 leads에도 — 채널별 리드 수·캡처 전환·가입 전환(`converted_user_id` 연결 필요). 가입 시 이메일 매칭으로 리드↔user 잇는 훅(`auth` 가입 경로에서 `Lead.email==user.email` 업데이트) 추가 예정.

---

## 6. 로드맵 (선착수 금지 순서)

1. **[지금] Phase 1 배포** — `./deploy.sh deploy` → 마이그레이션·엔드포인트·정적 웹 반영. GA4 관찰 시작.
2. **리드→가입 연결 훅** — 가입 시 동일 이메일 Lead에 `converted_user_id`·`nurture_status="converted"` 기록(전환 측정의 전제).
3. **admin 리드 대시보드** — 채널별 리드·전환 집계(attribution 패턴 재사용).
4. **육성 발송(Phase 2)** — SES 도메인 인증 + 알림톡 템플릿 심사 병행 신청 → `services/nurture.py` 어댑터 → Celery 스케줄.
5. **익스텐션 오버레이 진단 CTA** — 익스텐션 재제출 묶음에 포함.
6. **자격 판정 정밀화** — 구조화 자격필드·첨부 파싱 축적으로 제목 키워드 추정 보완.

---

## 7. 운영 주의 (함정)

- **'낙찰률' 문구 금지**(전역 규칙) — 진단·육성 카피 전부 "넣을 수 있는(자격)"·"안전" 프레임 유지. 승률·적중률 암시 금지.
- **개인정보** — 리드 연락처는 공고 알림·서비스 안내 용도 명시 + opt-out 필수(페이지 하단 고지 반영됨). 육성 발송 전 **수신동의·정보통신망법** 검토.
- **레이트리밋** — 공개 엔드포인트라 IP 기준(diagnose 40/h, capture 15/h) + nginx `limit_req zone=api`. 스팸 리드 유입 시 캡처 한도·이메일 검증 강화 검토.
- **SES 미구축·알림톡 미승인 상태에서 "알림 보내드려요" 카피의 약속 이행** — Phase 2 발송이 붙기 전 대량 캡처되면 수동 대응 필요. 초기 볼륨 낮을 때 배포하는 것이 안전.
```
