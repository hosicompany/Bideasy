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

### 3-1. 수신동의 증적 — **배포 완료(2026-07-30, PR #47 · 라이브)**

발송 어댑터보다 **먼저** 지은 이유: 정보통신망법 제50조는 광고성 정보 전송의 수신동의 사실을
**전송자가 증명**하도록 한다. 동의 없이 쌓인 연락처는 발송 순간 법적 리스크가 되므로, 증적
구조가 없으면 SES 승인이 나도 보낼 수 없다.

| 층 | 구현 | 위치 |
|---|---|---|
| 문구 정본 | 목적별·버전별 동의 문구 + sha256 지문. 과거 버전 영구 보존 | `backend/app/services/consent.py` (`CONSENT_TEXTS`) |
| 증적 로그 | `consent_records` — **추가 전용**(수정·삭제 API 없음). 주체·연락처 스냅샷·목적·행위(grant/withdraw)·문구버전·해시·출처·IP·UA | `models.ConsentRecord`, 마이그 `f4c1e8a92b37` |
| 현재 상태 | `Lead`/`User`: `marketing_consent`·`*_consent_at`·`*_withdrawn_at`·`marketing_confirmed_at`·`consent_text_version`·`consent_ip`·`consent_user_agent` | `models.py` |
| 발송 판정 | `can_send_marketing()`(단건) / `sendable_filter()`(쿼리) — 동의 True · 철회 없음 · **2년 내 확인**(제50조 제8항) | `services/consent.py` |
| 화면 | `/diagnose` 캡처 폼: [필수] 개인정보 수집·이용 + [선택] 광고성 정보 수신, **사전 체크 없음**·전문 토글. `/signup`: [선택] 수신동의 | `infra/nginx/html/diagnose.html`·`signup.html` |
| 조회 | `GET /admin/consents`(연락처 검색) · `GET /admin/consents/summary`(발송 가능 규모) · `/admin/leads/stats` 에 `sendable_leads` 추가 | `endpoints/admin/consents.py` |

**규칙 (발송 코드가 지켜야 할 계약)**
1. 광고성 발송은 **반드시** `can_send_marketing`/`sendable_filter` 를 통과한 대상에게만. `marketing_consent == True` 만 보고 자체 판단하지 않는다(철회·2년 만료가 누락됨).
2. 거래 관련 안내(결제·영수증·체험 만료 고지)는 광고가 아니므로 이 동의와 무관하게 발송한다.
3. 문구 수정 시 **새 버전 키 추가**(기존 삭제 금지) + 화면 `data-consent-version` 동반 갱신. `tests/test_consent.py::TestConsentTextDrift` 가 화면↔서버 문구 드리프트를 깨뜨려 알려준다.
4. **기존 리드는 전부 미동의로 시작한다** — 마이그레이션 기본값 false. 2026-07-30 이전 캡처분(동의 UI 이전)은 광고성 발송 대상이 아니다. 접촉하려면 재동의를 받아야 한다.
5. 구버전(캐시된) 페이지가 동의 필드 없이 제출하면 캡처는 되지만 증적이 없어 자동으로 발송 대상에서 빠진다.

### 3-2. 발송 파이프라인 — **가동 완료(2026-07-30, PR #47 · 전송 ON · 실발송 검증됨)**

동의 층 위에 발송 경로를 얹었다. 상세 런북(= AWS 준비·켜는 순서·함정) = **`docs/OUTBOUND_EMAIL.md`**.

- `services/nurture.py` — **유일한 발송 진입점**. 게이트(동의) → 멱등 선점 → 렌더 → 전송 → 원장.
- `services/mailer.py` — SES `send_raw_email`(원클릭 수신거부 헤더 때문에 raw 필수). `OUTBOUND_EMAIL_ENABLED=False` 면 dry-run.
- `services/email_templates.py` — 템플릿이 법정 표기를 잊을 수 없게 공통 조립기가 "(광고)" 접두·발신자·수신거부를 강제. 현재 `lead_welcome`(광고) / `trial_expiry`(거래).
- 수신거부 — 무기한 서명 토큰(`core/signed_token.py`) + `GET /unsubscribe/status`(조회) · `POST /unsubscribe`(처리, 원클릭 포함) + 정적 페이지 `/unsubscribe`.
- 원장 `OutboundMessage`(마이그 `a9d3f5c17e42`) — 보낸 건과 **차단된 건**(`no_consent`·`no_email`·`duplicate`) 전부 기록. `dedupe_key` 유니크로 중복 발송 차단.
- 운영 `GET /admin/outbound`(원장·집계·킬스위치 상태) · `GET /admin/outbound/preview` · `POST /admin/outbound/test-send`(본인 계정, 게이트 그대로).

**라이브 실증(2026-07-30)**: 거래 템플릿 실제 1통 `sent`(CloudWatch Send 1·Delivery 1·Bounce 0·Complaint 0), 미동의 광고메일 `skipped/no_consent`, 서명 토큰 정상 200·변조 400. 발송 전용 IAM `bideasy-ses-sender` + 서버 `OUTBOUND_EMAIL_ENABLED=true`.

**다음 단계**: 반송·불만 자동 억제(SNS 구독 — 시퀀스보다 먼저) → 리드 육성 시퀀스(진단 직후 웰컴 + 주기 매칭) → 체험 시퀀스(`GROWTH_STRATEGY.md` §C3) → 수신거부 처리 결과 통지 → 알림톡 어댑터.

### 3-3. 리드 육성 시퀀스 — **구현 완료(2026-08-01)**

동의·발송·억제 3층이 갖춰졌으므로 퍼널 ③(육성)을 실제로 켰다. 접촉은 **2회뿐**이다:
캡처 직후 웰컴 1통, 그 뒤 주 1회 신규 매칭.

| 시점 | 템플릿 | 성격 | 멱등 키 |
|---|---|---|---|
| 캡처 직후(동기) | `lead_welcome` | 광고 | `lead_welcome:lead:{id}` |
| 매주 화 08:00 KST | `lead_new_matches` | 광고 | `lead_new_matches:lead:{id}:{YYYY}W{주차}` |

| 항목 | 위치 |
|---|---|
| 매칭 단일 소스 | `backend/app/services/lead_matching.py` — `match_notices(..., since=)`. 진단 화면과 육성 메일이 **같은 기준**을 쓴다 |
| 웰컴 발송 | `endpoints/leads.py` `_send_welcome` — 캡처 커밋 **이후** best-effort |
| 주기 발송 | `backend/app/tasks/nurture_tasks.py` `nurture.send_lead_matches` (beat `weekly-lead-nurture`) |
| 템플릿 | `services/email_templates.py` `lead_new_matches` |
| 테스트 | `tests/test_lead_nurture.py` (10건) |

**설계 판단 3가지**

1. **웰컴은 큐가 아니라 인라인.** 이 코드베이스는 API 에서 Celery 를 호출하지 않는다(패턴 0건).
   큐를 새로 도입하는 대신 동기 발송하되, **커밋 이후에 `try/except` 로 감쌌다** — 발송 실패가
   리드 저장을 되돌리면 어렵게 얻은 연락처를 메일 한 통 때문에 잃는다. 응답은 수백 ms 느려진다.
2. **주 1회.** 반송률 5%·불만율 0.1% 초과 시 AWS 가 계정 발송을 정지시키고, 그러면 광고뿐 아니라
   **거래 메일까지 막힌다.** 리드 모수가 작은 지금은 빈도를 올려 얻을 것보다 잃을 것이 크다.
   빈도는 나중에 올리기 쉽지만 스팸으로 인식된 신뢰는 되돌리기 어렵다.
3. **신규 매칭이 0건이면 보내지 않는다.** 빈 메일은 그 자체가 스팸이다. 대상 조회는
   `sendable_filter` + 전환 리드 제외(회원 알림과 중복 방지)까지만 하고, 동의·억제·멱등의
   최종 판정은 `nurture.send_marketing` 이 한다 — 태스크가 `marketing_consent` 를 직접 보지 않는다.

⚠️ **소급 발송 없음**: 대상은 `sendable_filter` 통과분뿐이다. 2026-07-30 이전 캡처분은 증적이
없어 자동으로 빠진다(현재 `leads` 0건이라 실질 모수는 새로 들어오는 리드부터).

⚠️ 현재 `leads` 0건 — 광고 발송 모수는 새 동의자부터 쌓인다. 7/30 이전 캡처분 소급 발송 금지.

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
