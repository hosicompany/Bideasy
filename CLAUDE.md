# BidEasy — 개발 가이드 & 핸드오프 문서

> **이 문서가 BidEasy의 유일한 정본(Source of Truth)입니다.** OneDrive `Coding\MyProject\01_Bid Easy\CLAUDE.md`는 구버전(Flutter 시절) — 참조 금지.
> **새 세션은 이 문서 + `git log --oneline -30` 을 먼저 읽으세요.** 코드 전반의 맥락·결정·현재 상태·대기 작업이 여기에 정리돼 있습니다.
> 최종 갱신: 2026-07-18 세션2 (**리드→가입 전환 훅 + 어드민 리드 대시보드**(PR #27) + **자격 판정→처방**(안전망 레이어 ③, PR #28) — **머지 완료·⚠️배포 대기**. 도메인 리뷰 3건 사용자 승인[처방 문구·UNKNOWN 표시·다건 전환 집계]. 같은 날 세션1 = 벤치마크 G3 + 수습 3건 PR #26 배포·라이브 검증 완료 / 다음 = 배포 → 전환율 관찰 → 콘텐츠 엔진 Phase1 또는 반복낙찰 경보 스파이크)

---

## 0. 한 줄 정체성

**공공 입찰(나라장터/G2B) 분석·투찰 비서.** 크롬 익스텐션 + 웹앱(bideasy.kr) + 공유 FastAPI 백엔드로 구성된 3-Tier SaaS. "잃지 않게 지켜주는 입찰 안전 비서"가 브랜드 포지션 — **낙찰가 예측은 하지 않고**(신뢰 보호), 요약·독소조항·자격·계산·축적분석에 집중.

---

## 1. ⚡ 현재 상태 (핸드오프)

### 제품 실체 (셋이 한 백엔드·계정 공유)
| 채널 | 역할 | 위치 |
|---|---|---|
| **크롬 익스텐션** | 나라장터 페이지 위 오버레이 — 보고 있는 공고를 즉시 분석 | **별도 레포** `Bideasy-Extension/` (이 폴더 아님) |
| **웹앱** bideasy.kr | 어디서나·모바일·검색·발견. 공개검색(SEO) + 로그인 도구 | `infra/nginx/html/*.html` + 백엔드 SSR |
| **백엔드** api.bideasy.kr | FastAPI. 익스텐션·웹 공통. JWT 계정 공유 | `backend/` |

### 지금까지 완료된 큰 줄기 (전부 prod 배포됨)
- **결제(빌링) 시스템** — 토스 + **페이플** PG 다중화 (`PAYMENT_PROVIDER` 플래그). 14일 Pro 체험, win-back 할인, Celery 자동갱신. → §6 상세
- **웹 제품화 Phase 1~4** — 공개검색(`/search`), 공고상세 SSR(`/bid/{no}`, SEO), 계산기, 관심공고, 마감추적, 대시보드, 다건비교, AI 패널
- **A값 3-tier 자동수집** — 익스텐션 크라우드소스 → 첨부파싱 → (스크랩). `Notice.a_value` 캐시
- **자격매칭** — `QualificationChecker` 단일소스, 뱃지
- **관리자 대시보드** — 일일리포트·사용자·결제/환불·정확도·자가보정·시스템·시뮬레이션
- **자가보정(autocalibrate)** — 누적 개찰결과(DB) 병합한 백테스트·전략 재보정 (Celery 주간)
- **페이플 운영 라이브 (6/17)** — `PAYMENT_PROVIDER=payple` 실매출 가능, 실결제 24,900원 승인 검증. 환불은 페이플 콘솔 수동(`PCD_REFUND_KEY` 미연동), 콘솔 취소↔DB 동기화 없음(웹훅 없음). 윈백 50%는 "체험 만료 후 grace 7일 내 미결제자"에게만
- **보안 하드닝 (6/19, head `a3c7e1f9b204`)** — JWT `token_version` 무효화, 빌링키 Fernet 암호화, SSRF 가드, 정적 웹 XSS 이스케이프(`BD.esc`), OAuth state, 레이트리밋, 컨테이너 비-root(uid 10001), 페이플 콜백 CST_ID/금액/멱등 검증, AI한도 Redis. 보고서 `docs/SECURITY_AUDIT_2026-06-19.md`.
  - **`BILLING_ENC_KEY` 운영 설정·암호화 라이브 검증 완료**(서버 `.env.production`) — **분실·변경 절대 금지**(변경 시 기존 빌링키 복호화 불가). 미설정이면 평문 폴백. 비-root 전환으로 신규 볼륨 배포 시 `strategy_data`/`celerybeat_data` `chown 10001` 필요.
- **검색엔진 등록 (6/16)** — Google·Naver 소유확인 + 사이트맵 제출 (루트 HTML 파일 방식)
- **웹스토어 ASO + UTM 귀속 (6/20~22)** — 스토어 listing 캐논 `docs/STORE_LISTING.md`, first-touch UTM(`users.signup_source` 등, 마이그레이션 `c4f8a1e7d602`) + `GET /admin/stats/attribution`
- **랜딩 전환 최적화 개편 (2026-07-08 배포)** — `index.html`: 인터랙티브 미니 계산기(+Pro 지표 blur 잠금)·익스텐션 사용 장면 목업·유스케이스 페르소나(가짜 후기 아님, 상황 기반)·창업자 스토리·경쟁 비교표(A예측형/B알림형/C수기 익명 유형, ✓/△/✕·"특정 업체 아님" 캡션)·FAQ(+FAQPage 스키마, 첫 질문=비예측)·CTA GA4 이벤트(`cta_*`·`calc_demo_use`). 정직·비예측 포지션 유지.
- **런칭 기념가 개편 (2026-07-08 배포)** — Pro 24,900→19,900, Pro+ 49,900→39,900 (연 191,000/383,000, 윈백 첫 달 Pro 9,950/Pro+ 19,950). §12 반영. 결정 근거·경쟁사 앵커 → 메모리 `pricing-launch-2026-07`·`competitor-dimatools`.
- **checkout 익스텐션 호환 픽스 (2026-07-08 배포)** — 웹 `checkout.html`이 익스텐션발 파라미터 수용: `plan=`→`tier=` 별칭(Pro+가 Pro로 가던 버그)·`#token=` fragment 수용(비로그인 이탈 방지)·`type=points`→`/account`. 익스텐션 코드 미변경(웹이 흡수 → 웹스토어 재심사 불필요).
- **무료 자격 진단 리드 마그넷 (2026-07-09 배포·라이브)** — 비로그인 방문자 업종·지역 입력 → `QualificationChecker`로 활성 공고 자격 필터 → 매칭 수·상위 3건 미리보기 → 연락처 캡처(`Lead` 저장+전체 잠금해제). `Lead` 모델+마이그 `d9f3a1b7c204`, `POST /leads/diagnose|capture`(공개·IP 레이트리밋, XFF 마지막 홉), 웹 `/diagnose`+랜딩 hero CTA(`cta_hero_diagnose`)·UTM/GA4(`lead_diagnose`·`lead_capture`). 육성(카카오 알림톡+SES 병행 pluggable)·익스텐션 오버레이 진단 CTA는 **설계만**(`docs/LEAD_ACQUISITION.md`). ⚠️→✅ 콜드-DB 이슈는 07-10 워밍으로 후속 해소(아래 줄) — **단 미배포**.
- **블로그 예약·유예 자동발행 (2026-07-09 배포)** — 발행이 사람 1클릭 의존이라 26일째 신규 0편이던 문제 해결. `content.publish_scheduled`(매시 :05)가 `publish_at` 도래한 draft 자동발행. 데이터스토리 자동초안엔 `publish_at=생성+48h` 유예 부여(`BLOG_AUTOPUBLISH_GRACE_HOURS`=48, 0=킬스위치). 상록수·입찰상식은 어드민 `/admin-blog` **예약 입력(신설)**으로 드립. unpublish·PUT→draft 시 예약 해제(재발행 방지), tz-aware→naive UTC 정규화. **마이그 불필요**(`publish_at` 기존 `e1a4c7b2f039`). ⚠️ 배포 시 `celery_beat` 수동 force-recreate 필수(안 하면 새 스케줄 미등록).
- **콘텐츠 엔진 설계 확정 (2026-07-09, 문서)** — `docs/CONTENT_ENGINE.md`: 1 주제→1 구조화 정본(훅·요약·핵심·데이터·CTA)→N 채널(블로그·인스타·유튜브·**네이버블로그 요약형**) OSMU. **입찰상식(Track K) 시드 24개**(정직·비예측·안전 프레임). 자동화 경계=텍스트 자동/시각물 반자동(/cardmaker)/업로드 사람. SEO=네이버·구글 이원화·스팸정책 방어·FAQPage/HowTo/VideoObject·유튜브 자막. **구현 전(설계).**
- **진단 콜드-DB 워밍 (2026-07-10 · PR #24 머지·배포 완료)** — `/leads/diagnose`가 DB만 읽어 일일 크롤 전 콜드 스타트면 실방문자에게 "매칭 0건" 오인. `_match_notices` 진입점에서 `_warm_db_if_cold`: 활성(마감 전·non-Mock) 공고 0건이면 1회 크롤 워밍(fetch→save). **운영 전용 가드**(`APP_ENV=production`만 — dev/test는 시딩), **스탬피드/DoS 락**(Redis `SET NX` TTL 600s → Redis 미가용 시 프로세스 로컬 타임스탬프 폴백), 크롤 실패 비치명적. 테스트 `TestColdDbWarm` 3종 통과. `backend/app/api/v1/endpoints/leads.py:163`. *(구 핸드오프 "미커밋·미배포"는 오기 — 실제로는 07-10 머지·배포됨.)*
- **백필 검증 probe 확정 (2026-07-10, 문서·스크립트)** — `docs/BACKFILL_VALIDATION_DESIGN.md` §3: 개찰 카테고리 코드 **공사3/용역5/물품1**, 응답 스키마 3종 동일(38필드 → `_parse_item_to_kwargs` 재사용), **API 조회범위 ≤24h**(하루 창·start·end 실제시각), 하한율은 API 레코드별 제공(`sucsfLwstlmtRt`), 물품은 최저가라 안전 무효율 N/A. 스크립트: `census_construction.py`(표본 vs 전수 ground truth), `diag_crawl.py`·`diag_hist.py`(API 진단), `probe_bsns_div.py`(30일→1일 창 수정). **실행은 서버(`PUBLIC_DATA_KEY`)에서 후속.**
- **운영 위임 런북·광고 검증 문서 (커밋 정리 대기)** — `docs/AGENT_OPS_RUNBOOK.md`(Hermes 에이전트 권한 3등급 계약 🟢AUTO/🟡APPROVE/🔴HUMAN), `docs/AD_CAMPAIGN_VALIDATION.md`(네이버 검색광고 A/B 캠페인 패키지 — 집행 보류 중, SERP 정찰·소재 A안전/B자격필터). 둘 다 untracked → 커밋 정리 필요.
- **경쟁 전략 정본 + 낙찰 도달 벤치마크 + 정직성 수습 3건 (2026-07-17~18 · PR #26 머지·배포·라이브 검증 완료)** —
  ① **전략 정본** `docs/COMPETITIVE_STRATEGY.md`: 3사(디마툴즈·지투비플러스·비드프로) 딥리서치 검증 → 가격 인하 대신 **"입찰 안전망" 4레이어**(투찰 안전 게이트/안전 밴드/자격 처방/반복낙찰 경보)로 value 심화·가격 유지. 해자 3종(익스텐션 유통·비예측 정직·데이터 플라이휠). 기능 결정은 이 문서 통과 필수.
  ② **벤치마크** `docs/BENCHMARK_WIN_REACH.md` + `backend/scripts/benchmark_win_reach.py`: 게이트 **사전 등록** 후 실측. **판정 G3(포지션 유지)** — 단 **적격심사제에서 현 active 전략이 이미 이론 상한의 92%**(2025 win 41.5% vs oracle 45.3%). 격차는 모델이 아니라 노출(`recommend_bid_price` API 미노출이었음). 소액수의견적 2024 레짐 변화(oracle 5.6%→36.8%) 발견 — 과적합 아님(walk-forward ≤2.5%p). **"25% 상한" 마케팅 주장 금지**(레짐 분해로 거짓). 디마 반박: 우리 표본 상한 37~45% — 63~65%는 모수가 다름. **전략투찰(Pro+) 제품화는 2026 개찰 400건+ 누적 후 G2 재판정 조건부**.
  ③ **수습 3건**: 합성데이터 공개 엔드포인트 제거(`winning_rate.py` — "Demo Mode" 가짜 통계 → insufficient_data 명시) · 낙찰하한율 단일 소스 `lower_limits.py`(2026-01-30 개정 금액대 티어 — 10억 미만 공사 89.745%, **소액 공사 DANGER 판정이 정확해짐**, 라이브 검증 완료) · smart-bid 죽은 ML 스택 수습(`/recommend`를 autocalibrate 룰기반 대체[공사만, 물품·용역 503], 나머지 ML 엔드포인트 500+에러누출 → 정직한 503). 신규 테스트 19건, 총 359건 통과.
  ⚠️ 잔여: ML 재구축은 벤치마크상 룰기반 우위라 보류. Pro+ 기능 목록/가격표에서 "공사 전용" 표기 정합성 별도 검토.
- **리드→가입 전환 훅 + 자격 처방 (2026-07-18 세션2 · PR #27·#28 머지 · ⚠️배포 대기)** —
  ① **전환 훅**(#27): `services/lead_conversion.py` `link_leads_to_user` — 가입(이메일·소셜 신규) 시 동일 이메일 Lead 를 `converted_user_id`+`nurture_status='converted'` 기록. 이메일 정규화(소문자·trim) 조회 시점 매칭(양쪽 저장 정규화 없음), 동일 이메일 다건 전부 전환(사용자 승인), best-effort 이중 가드(가입 절대 안 막음). 어드민 `GET /admin/leads/stats`(총/전환율/업종/일별/최근). 스키마 변경 없음(컬럼 기존 마이그에 존재). 부수: `test_ai_analysis` 리미터 teardown 누수(enabled=True 복구 → 뒤 테스트 429) 수정.
  ② **자격 처방**(#28, 안전망 ③): `QualificationChecker`에 `prescriptions`(requirement/issue/action/confidence) 추가 — **데이터 있는 요건만**(지역 확정·면허 "공고명 추정" 명시·프로필), 실적·시공능력은 공고 기준액 부재로 처방 안 함(후속 파이프라인). **프로필 미기재 = FAIL→UNKNOWN(판정 불가) 정직화**(사용자 승인, 추천배치·진단은 PASS만 봐서 행동 불변). `details` 문자열·뱃지 하위 호환 유지(5개 호출처 무변경). ai.py tip 처방 연동+ℹ️ UNKNOWN, bid.html "이렇게 하면 참여할 수 있어요" 블록. 디마 연 99만원 적격진단의 기본 제공 언더컷. 총 378건 통과.

### ⏳ 대기 중인 외부 작업 (코드 아님, 사용자/제3자 처리)
| 항목 | 상태 |
|---|---|
| **토스 MID 심사** | 진행 중 — 페이플 운영 라이브(6/17)로 긴급성 낮음, 병행 가능 |
| **Chrome 웹스토어** | ASO 개정판 검토 제출(6/20). ⚠️ **listing 가격 문구 24,900→19,900 갱신 필요**(런칭 기념가). 툴바 아이콘 `npm run build` + 재제출 대기 |
| **익스텐션 코드 정리** | `plan→tier` 파라미터 정리 + 포인트 버튼 처리 → 다음 재제출에 포함. **지금은 웹 checkout이 흡수해 급하지 않음** |
| **익스텐션 A값 Tier1 활성화** | 웹스토어 승인 후 |
| **OpenAI 키·POSTGRES_PASSWORD 로테이션** | ⚠️ 미완 — 6/19 감사에서 노출 확인, 사용자 처리 필요 |

### 2차 = 고객 검증 (GTM 진행 중 — 상세: 메모리 `bideasy-gtm-strategy`)
- **비치헤드 확정** (2026-07-07): 전문건설(전기공사 먼저) 1~10인, **월 10건+ 직접 투찰**(빈도 기준). 훅=자격필터 / 지갑=안전 투찰. 물품은 하한선 없어 안전게임 아님(제외).
- **검증기계(전화 0통)**: 네이버 검색광고 A/B(안전 vs 자격필터 훅) — 캠페인 패키지 완성, **집행 보류 중** → `docs/AD_CAMPAIGN_VALIDATION.md`. 측정 = first-touch UTM + GA4 + `/admin/stats/attribution`.
- **census 전수조사 = 하지 않음** — 공사 개찰 169k행/일이라 전수는 함정. sample≈census는 통계로 보장. (개찰 API: window ≤24h·시작도 실제시각·num_rows 작게. 코드 `3/5/1`=공사/용역/물품.)
- 남은 검증 코드: 가입 직후 1문항 마이크로 설문(업종·월 투찰수) + 커뮤니티 질문글.

### 다음 주제 (후보)
- **콘텐츠 엔진 Phase 1** (`docs/CONTENT_ENGINE.md`) — 구조화 정본 생성 엔진(주제 큐 소비→AI 초안→검수→`publish_at` 드립) + **입찰상식 24개를 `docs/CONTENT_CALENDAR.md`에 Track K로 이관**. `BlogPost`에 `blocks_json`/`channel_assets_json` 컬럼 검토(가벼운 마이그). 이후 Phase2=채널 텍스트 파생, Phase3=시각물 반자동.
- **콜드-DB 워밍 PR·배포 (최우선)** — 브랜치 `fix/lead-diagnose-cold-db-warm`(코드·테스트 완료) 커밋→PR→**사용자 확인 후 머지·배포**. 배포 후 실방문자 진단 0건 오인 해소 확인. 워킹트리에 함께 있는 백필 문서·census/진단 스크립트·런북(untracked)도 커밋 정리.
- **리드→가입 전환 훅** — 가입 시 동일 이메일 `Lead.converted_user_id`·`nurture_status="converted"` 기록 + 어드민 리드 대시보드(attribution 패턴 재사용). 전환 측정의 전제.
- **육성 발송 인프라** — 카카오 알림톡 템플릿 심사 + AWS SES 도메인 인증(외부 리드타임) → `services/nurture.py` 어댑터. 리드 쌓이기 시작하면 병행 신청.
- **익스텐션 재제출** — `plan→tier` 정리 + 포인트 버튼 + 툴바 아이콘 빌드 + **오버레이 진단 CTA**(리드 마그넷 연동) → Chrome 웹스토어 재제출 (listing 가격 문구도 19,900 갱신).
- **랜딩 개편 효과 측정** — GA4에서 `cta_*`·`calc_demo_use`·`lead_diagnose`·`lead_capture` 전환율 관찰. 데이터 보고 개선 반영.
- **랜딩 A/B 훅 실험** — 안전 vs 자격필터 훅 A/B는 **미착수**(광고 검증 캠페인과 연동, 현재 집행 보류). 이번 랜딩 개편은 전환 구조까지만 완료.
- **CI green 복구** — `lint`(ruff 25개 기존 오류)·`flutter` 상시 red 정리 (2026-07-08 별도 세션 task 진행 중).

### 이후 (고객 검증 통과 후, 선착수 금지)
- 자가학습 안전비서 Phase1(`UserBid`↔`OpeningResult` 피드백 루프)
- Pro+ ML 웹 노출, 웹푸시(FCM), 윈백 이메일 인프라(SES — 이탈자는 앱내 알림으로 안 닿음)
- (6/22) UTM 마이그레이션 배포·마케팅 링크 UTM 태깅·Cloudflare Web Analytics — 완료 여부 확인 필요

> 세션 루틴: 새 세션 `/kickoff` → 작업 → `/handoff` (전역 슬래시 명령, 2026-07-07 신설).

---

## ⚠️ 함정·금지 목록 (필독 — 위반 시 운영 사고)

1. **`BILLING_ENC_KEY` 변경·재생성 절대 금지** — 변경/분실 시 암호화된 빌링키 전부 복호화 불가(고객 전원 재카드등록). `infra/.env.production`에만 존재, 안전 백업 필수.
2. **KPI·마케팅에 '낙찰률' 사용 금지** — 개찰데이터 검증 결과 승률 지표는 과적합(8%→23%) + 사정률 추첨은 랜덤. 핵심 지표 = 유효율 95% + 입찰당 재사용률.
3. **`deploy.sh`가 안 하는 것**: `celery_beat` 재생성 안 함 → 새 코드 반영은 수동 `docker compose -f docker-compose.prod.yml --env-file .env.production -p infra up -d --force-recreate celery_beat`.
4. **config fail-fast**: `APP_ENV=production`에서 `JWT_SECRET_KEY` 미설정 또는 `POSTGRES_PASSWORD=bideasy_pass`(기본값)면 앱 기동 실패.
5. **비-root 컨테이너(uid 10001)**: named 볼륨(`infra_strategy_data`·`infra_celerybeat_data`)이 root 소유면 백그라운드 워커 쓰기 실패. 최초 1회 `docker run --rm -v <볼륨>:/d alpine chown -R 10001:10001 /d`.
6. **헬스체크 10초 오탐**: deploy.sh는 app 재생성 10초 뒤 체크 → `WARNING: Health check failed`는 대개 오탐. 진짜 상태는 `https://api.bideasy.kr/health`(200 + `database:connected`).
7. **app 수동 재생성 시 nginx reload 필수** — 도커 IP가 바뀌어 nginx가 옛 IP로 502. `./deploy.sh deploy`는 자동 처리(수동 compose up 시 누락 주의).
8. **페이플 콜백 리다이렉트는 303** (307이면 정적 `/account`에 POST 재전송 → nginx 405).
9. **버전 표기**: 현재 v1.2 (2026-07-08 랜딩 개편 시 v1.1→v1.2) — 변경 성격(MAJOR/MINOR/PATCH)을 판단해 랜딩 푸터에 반영.

---

## 2. 기술 스택

- **백엔드**: FastAPI(async) + SQLAlchemy + Alembic. **PostgreSQL(prod) / SQLite(test·로컬)**. Celery + Redis(beat 스케줄). Jinja2(SSR).
- **AI**: OpenAI `gpt-4o-mini`(요약·독소조항), 심층분석 `gpt-5-nano`→`gpt-4o-mini` 폴백. **기본 "팁"은 규칙기반**(`tips_generator`, 비-LLM). LLM은 **공고 본문(content)이 있을 때만** 발동.
- **웹 프론트**: **vanilla HTML + nginx 정적** (프레임워크 없음). 공통 `assets/nav.js`·`api()`·`getToken()` 재사용. 공개 페이지는 SEO 위해 SPA 금지.
- **모바일 앱**: Flutter(Riverpod) — `frontend/`. *현재 주력은 익스텐션+웹. Flutter 앱은 부차.*
- **익스텐션**: TypeScript (별도 레포 `Bideasy-Extension/`).
- **인프라**: Docker Compose, nginx 리버스프록시, Let's Encrypt, AWS Lightsail.

---

## 3. 디렉토리 구조 (실제)

```
Bideasy/
├── backend/
│   ├── app/
│   │   ├── api/v1/endpoints/   # 라우터 (아래 §4)
│   │   │   └── admin/          # accuracy/autocalibrate/dashboard/payments/simulation/system/users
│   │   ├── core/              # config.py, security.py, celery_app.py, analytics.py, logging.py
│   │   ├── db/                # models.py(ORM), session.py, base.py
│   │   ├── schemas/           # subscription.py(가격·티어·체험), bid.py, payment.py ...
│   │   ├── services/          # 도메인 로직 (아래 §5)
│   │   └── tasks/             # Celery 태스크 (아래 §5)
│   ├── alembic/versions/      # 마이그레이션 (head: d9f3a1b7c204 — leads 테이블)
│   ├── templates/             # bid_detail.html (SSR)
│   ├── tests/                 # pytest (359건)
│   └── main.py                # 앱 진입점 (+ /bid/{no}, /sitemap.xml 마운트)
├── infra/
│   ├── docker-compose.prod.yml
│   ├── deploy.sh              # ★ 배포 진입점 (§7)
│   ├── .env.production        # ★ 비밀키 (git 제외, 서버에만)
│   └── nginx/
│       ├── conf.d/            # default.conf(웹), api.bideasy.kr.conf
│       └── html/              # 웹 페이지 (account/admin/calculator/compare/dashboard/
│                              #   favorites/guide/index/login/pricing/search/signup/terms)
├── frontend/                  # Flutter 앱 (부차)
├── docs/                      # design/ product/ technical/ TROUBLESHOOTING.md
└── claude.md                  # ← 이 문서
```
> **크롬 익스텐션은 이 폴더에 없음** — 사이드 레포 `Bideasy-Extension/`.

---

## 4. 백엔드 — 엔드포인트 그룹

`backend/app/api/v1/endpoints/` (전부 `/api/v1/*` 마운트):

| 파일 | 핵심 책임 |
|---|---|
| `auth.py` | 회원가입/로그인(JWT), 소셜(kakao/naver) |
| `users.py` | 프로필(면허·지역·시공능력·실적), `/users/me`, `/users/me/trial` |
| `bids.py` | **피드/검색(`get_feed`, DB-merge)**, 계산, 관심(favorite), 추적(track), 자격(qualification), A값(`PUT /{no}/a_value`, scrape-avalue), context/batch-context |
| `ai.py` | AI 분석(요약·독소조항). 자격블록은 캐시분리(누수수정). 레이트리밋(Free 1회/일) |
| `analysis.py` | 첨부 심층분석(Deep, Pro+) |
| `payments.py` | **결제·구독** — 토스 billing + **페이플** prepare/callback + `/provider`. §6 |
| `points.py` | 포인트 |
| `agency.py`·`smart_bid.py`·`prediction.py` | 기관 프로파일·ML(경쟁예측·사정률·추천) — Pro/Pro+ |
| `pages.py` | **SSR** 공고상세 `/bid/{no}` + `/sitemap.xml` (SEO 핵심) |
| `notifications.py` | 인앱 알림 |
| `health.py` | `/health` |
| `admin/*` | 관리자 전용 (`require_admin` 가드) |

---

## 5. 서비스 & Celery 스케줄

**핵심 서비스** (`backend/app/services/`):
- `calculator.py` — 투찰가 계산(핵심). `crawler.py` — 멀티카테고리(공사/용역/물품) fan-out 수집.
- `billing.py`(토스) / **`payple.py`(페이플)** — 빌링키 발급·청구. `payments_refund.py` — 환불.
- `qualification_checker.py` — 자격 판정(PASS/FAIL + 뱃지). `attachment_avalue.py` — A값 Tier2(첨부 HWP/PDF 파싱).
- `bid_detail.py` — 단건조회(inqryDiv=2 + 멀티카테고리). `opening_result*.py` — 개찰결과 누적.
- `llm_agent.py`·`ai_analyzer.py`·`document_parser.py`·`tips_generator.py` — AI 파이프라인.
- ML: `prediction_service.py`·`bidrate_prediction_service.py`·`participant_prediction_service.py`·`agency_profiler.py`·`simulation_service.py`·`winning_rate.py`.

**Celery beat 스케줄** (`core/celery_app.py`, 시각=KST):
| 시각 | 태스크 | 내용 |
|---|---|---|
| 03:00 | `billing.charge_due_subscriptions` | 자동결제 갱신 (토스/페이플 분기) |
| 06:00 | `notices.crawl_daily` | 일일 공고 수집 |
| 06:30 | `notices.backfill_avalue` | A값 Tier2 백필 |
| 07:00 | `recommend.send_matches` | 자격 맞춤 추천 발송 |
| 09:00 | `admin_report.send_daily` | 관리자 일일 리포트 |
| 10:00 | `trial.send_expiry_reminders` | 체험 만료 리마인드 |
| 10:30 | `deadline.send_reminders` | 마감 리마인더(D-3/1/day) |
| 19:00 | `verification.daily_crawl_opening_results` | 개찰결과 누적 |
| 20:00 | `verification.daily_verify_predictions` | 예측 검증 |
| 月 04:00 | `autocalibrate.recalibrate_strategy` | 전략 재보정 |
| 月 08:00 | `content.weekly_data_story` | 데이터스토리 주간 초안(유예 `publish_at` 부여) |
| 매시 05분 | `content.publish_scheduled` | 예약·유예 도래 draft 자동 발행 |
| 1일 05:00 | `notices.purge_old` | 오래된 공고 정리 |

---

## 6. 결제 시스템 (PG 다중화) ★

**핵심 결정**: 토스 MID 심사가 길어져, 정기결제 PG를 **토스/페이플 둘 다** 지원하도록 pluggable 구조로 만듦. `User.billing_provider`("toss"|"payple") 컬럼으로 자동갱신 시 어느 PG로 청구할지 결정.

- **활성 PG 전환**: `settings.PAYMENT_PROVIDER` (기본 `"toss"`). 프론트는 `GET /payments/provider`로 확인 후 분기.
- **토스 흐름**: `/billing/prepare` → `requestBillingAuth`(카드등록 리다이렉트) → `/billing/success`(빌링키발급+첫청구+티어적용).
- **페이플 흐름**: `/payple/prepare` → 프론트가 `payment.js`(v1)+jQuery 로드 → `PaypleCpayAuthCheck({PCD_PAY_WORK:'CERT', PCD_CARD_VER:'01', ...})`(오버레이) → 결과를 `PCD_RST_URL`(=`/payple/callback`)로 POST → 빌링키 저장+첫청구+티어적용 → `/account` 리다이렉트.
  - 서버청구: `payple.partner_auth('PAYM')` → `SimplePayCardAct.php?ACT_=PAYM`에 `PCD_PAYER_ID`(빌링키)+금액.
  - **검증됨**: 실 샌드박스(democpay) 파트너인증 성공 확인.
- **자동갱신** (`tasks/billing_tasks.py`): 만료 임박(D-1) 사용자 → provider 분기 청구 → 만료일 연장. 주문 prefix `BILLR_`(토스)/`PYPR_`(페이플). 실패 시 grace 3일 후 해지+Free 강등.
- **주문 ID 규칙**: `{PREFIX}_{uid}_{P|PP}_{m|a}_{ts}_{rand}`. 결제내역 분류는 prefix(`SUB_/BILL_/BILLR_/PYP_/PYPR_`)로.
- **주의**: 페이플 콜백에서 `payment_key`는 빌링키가 아니라 **고유 OID** 저장(빌링키는 재등록 시 재사용 → UNIQUE 충돌 방지).
- **페이플 운영 전환 절차** (가맹 승인 후): `.env.production`에 `PAYMENT_PROVIDER=payple`, `PAYPLE_IS_TEST=false`, 운영 `PAYPLE_CST_ID/CUST_KEY/CLIENT_KEY`, `PAYPLE_REFERER=https://bideasy.kr` → `./deploy.sh deploy`.

---

## 7. 배포 (Docker)

서버(Lightsail)에서 **백엔드는 Docker 컨테이너**로 구동 → `alembic`은 호스트 PATH에 없음(컨테이너 내부에만).

```bash
# 표준 배포 (코드 pull + 이미지 재빌드 + 롤링 재시작 + 마이그레이션)
cd ~/Bideasy/infra && ./deploy.sh deploy
```
`deploy.sh`가 자동 수행: `git pull origin master` → `dc build app celery_worker` → 롤링 재시작 → 헬스체크 → **`dc exec app alembic upgrade head`**.
- 기타: `./deploy.sh {status|logs|backup|rollback|ssl-init}`. 프로젝트명 `-p infra` 고정.
- 마이그레이션만 수동: `docker compose -f docker-compose.prod.yml --env-file .env.production -p infra exec app alembic upgrade head`
- **현재 마이그레이션 head**: `d9f3a1b7c204` (leads 테이블 — 무료 자격 진단 리드). 직전 `c4f8a1e7d602`(signup attribution) → `a3c7e1f9b204`(widen billing_key). *(이전 문서의 `c4f1a9e63b27`/`a3c7e1f9b204` 표기는 구버전 — 정정됨.)*

---

## 8. 테스트 — 검증 명령 (코드 변경 후 반드시 실행)

```bash
cd backend && pytest          # 359건 통과 기준 (2026-07-18. SQLite in-memory/파일)
```
- **모든 코드 변경 후 위 명령을 실행하고, 완료 보고(Gate Check)에 결과와 신뢰도(🟢🟡🔴)를 기재한다.** 실패 상태로 커밋·배포 금지. 실패 수정은 2회까지, 이후 에스컬레이션.
- 결제: `tests/test_billing.py`(토스), `tests/test_payple.py`(페이플 9건 — provider/prepare/callback/서비스청구/Celery갱신, HTTP 모킹).
- 그 외 feed/calculator/qualification/favorites/deadline/ai 등.

---

## 9. 🔒 보안 규칙 (반드시 준수)

1. **비밀키는 코드/git에 절대 없음.** 실값은 **서버 `infra/.env.production`에만** (git 제외). 토스/페이플/PUBLIC_DATA/OPENAI/JWT 키 전부.
   - 단, `config.py`의 페이플 값은 **공개 테스트 샌드박스 기본값**(실 운영키 아님).
   - `JWT_SECRET_KEY`는 `.env.production`에 **고정**해야 함(미설정 시 배포마다 전원 로그아웃).
2. **`PATENT.md` 절대 커밋·푸시 금지** (내부 IP). `.gitignore`에 `**/PATENT.md` 등록됨. `MORNING_CHECKLIST.md`·`OVERNIGHT_REPORT.md`도 동일.
3. **git push는 매번 사용자 명시 승인 후** 실행.
4. 관리자 계정: `hosicompany@gmail.com` (비번은 별도 보관).
5. 개인정보/자격결과 캐시 누수 주의 — `AIAnalysisLog` 캐시에 사용자별 자격 포함 금지(분리 처리됨).

---

## 10. 핵심 도메인 로직

- **투찰가 안전성**: 낙찰하한율 미만 → 무조건 `DANGER`. 1원단위 절사 `math.floor(price/10)*10`.
- **A값**(국민연금·건보·산재·고용·노인장기요양 합): **어떤 조달청 OpenAPI에도 없음**. 첨부문서/나라장터 DOM에만 → 3-tier 수집(익스텐션 보고 → 첨부파싱 → 스크랩) → `Notice.a_value` 캐시. 공사만 영향, 물품은 A값칸 숨김.
- **검색**: OpenAPI `bidNtceNm` 필터 불안정 → 키워드 관련도 post-filter + DB-merge(정적 `opening_results_*.json` + 누적 `OpeningResult` 테이블).
- **자가보정**: `load_records(db=)`가 정적+누적 병합 → 백테스트·전략 재보정.

---

## 11. 디자인 시스템 (웹/앱 공통 토큰)

```
primaryBlue  #3182F6   배경 #F2F4F6   surface #FFFFFF
textMain #191F28   textSub #8B95A1   safe #34C759   danger #FF3B30
```
- 폰트: Web/Android = Pretendard, iOS = System. 카드 Radius 20px / Border 1px #E5E8EB.
- 톤앤매너: **해요체·친근** ("사장님, 이 부분 조심하셔야 해요!"). 건조한 명사형 금지.

---

## 12. 가격 / 체험 (3-Tier SaaS)

| | Free | Pro | Pro+ |
|---|---|---|---|
| 월 | 무료 | 19,900원 | 39,900원 |
| 연 | — | 191,000원 | 383,000원 |
| AI 분석 | 일 1회 | 일 50회 | 무제한 |
| Deep분석·경쟁참고·투찰검증 | ❌ | ✅ | ✅ |
| 기관프로파일·안전가이드·사정률분포 | ❌ | ❌ | ✅ |

- 상수: `backend/app/schemas/subscription.py` (`MONTHLY_PRICES`/`ANNUAL_PRICES`/`TIER_*`).
- **2026-07 런칭 기념가 개편**: Pro 24,900→19,900(2만원 벽 돌파), Pro+ 49,900→39,900(1:2 사다리). 경쟁사(디마툴즈 무제한 33,000원) 대비 Pro 40% 저렴. 랜딩에 런칭 기념가 뱃지(구가 취소선) 표기. 윈백 첫 달 50% = Pro 9,950 / Pro+ 19,950. (6/17 실결제 24,900 기록은 개편 이전 값 — 위 §1.1 라이브 기록은 그대로 사실.)
- **14일 Pro 체험**: 가입 시 자동(카드 불요) → 만료 시 자동 Free. 재체험 불가(`trial_started_at` 영구). 결제 시 체험 종료. 통합판정 `get_effective_tier(user)`.
- **win-back**: 체험 후 미결제자 첫 달 50% 할인(`TRIAL_WINBACK_50`), 갱신엔 미적용.

---

## 13. AI 전략

- **Do**: 공고 요약(3줄), 독소조항 탐지, 과거데이터 팩트분석. **Don't**: 낙찰가 예측.
- 출력은 JSON 스키마(`summary_3_lines`, `risk_factors[type/content/severity]`, `overall_sentiment: SAFE|CAUTION|DANGER`).
- `temperature=0`(일관성). 결과는 `AIAnalysisLog` 캐싱(LLM 비용 절감, 단 자격블록 제외).
- **전제**: `OPENAI_API_KEY` 미설정 시 LLM 전부 실패 → 사실상 규칙기반만 동작.
```
