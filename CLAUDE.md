# BidEasy — 개발 가이드 & 핸드오프 문서

> **이 문서가 BidEasy의 유일한 정본(Source of Truth)입니다.** OneDrive `Coding\MyProject\01_Bid Easy\CLAUDE.md`는 구버전(Flutter 시절) — 참조 금지.
> **새 세션은 이 문서 + `git log --oneline -30` 을 먼저 읽으세요.** 코드 전반의 맥락·결정·현재 상태·대기 작업이 여기에 정리돼 있습니다.
> 🖥️ **새 PC에서 처음 세팅하는 중이라면** `docs/HANDOFF_MIGRATION.md` 를 먼저 읽으세요 (2026-08-01 PC 이관 — 비공개 파일 복원·`preserve/*` WIP 브랜치·환경 재구축). 셋업이 끝났으면 무시해도 됩니다.
> 최종 갱신: 2026-08-01 (**리드 육성 시퀀스 라이브** — PR #50 머지·배포·**E2E 실검증 완료**. 흐름: 진단 캡처 → **더블 옵트인 확인 메일**(거래) → 확인 클릭 → 웰컴(광고) → 매주 화 08:00 신규 매칭(광고). 설계 판단 5가지·표 = `docs/LEAD_ACQUISITION.md` §3-3. 요지: ① `services/lead_matching.py` = 진단 화면과 육성 메일의 **자격 판정 단일 소스**(`since` 로 신규만) ② `/leads/capture` 는 인증 없는 공개 폼이라 **확인 전 광고 금지** — `grant_marketing(confirmed=False)` → `marketing_confirmed_at` NULL → `sendable_filter` 가 차단, `POST /leads/optin` 으로만 확정(GET 은 스캐너 프리페치 방지 조회) + 정적 `/optin` ③ 멱등 주체 = **행이 아니라 수신자**(이메일 해시) — 캡처는 upsert 없이 매번 새 Lead 행을 만들기 때문 ④ `can_send_marketing` 의 `marketing_consent_at` **폴백 제거**(SQL 판본 `sendable_filter` 와 판정이 갈라져 있었음) ⑤ 실패는 1건에 갇힌다(입력 제어문자 정제 + `mailer` 조립실패도 `MailerError` 로 변환 + 배치 리드 단위 except + 실패 시 `dedupe_key` 해제). 테스트 527건. **E2E 실측**: 캡처 `confirm_pending=true`·광고 미발송 → 확인 메일 수신 → 클릭 → `(광고)` 웰컴 수신·수신거부 링크 정상. 다음 = 체험 시퀀스 6통 → 수신거부 처리결과 통지 → 알림톡 채널.)
> 직전 갱신: 2026-07-30 (**아웃바운드 3층 구축** — 수신동의 증적(`consent_records` 추가 전용·문구 sha256, 마이그 `f4c1e8a92b37`) → 발송 파이프라인(`nurture.py` 유일 진입점·`OutboundMessage` 원장·수신거부 서명토큰, 마이그 `a9d3f5c17e42`) → 반송·불만 자동 억제(PR #49, 마이그 `c8e5b1f37d94`). SES 프로덕션 승인 + 발송 전용 IAM `bideasy-ses-sender` + `OUTBOUND_EMAIL_ENABLED=true` 로 **실발송 검증 완료**. 상세 런북 = `docs/OUTBOUND_EMAIL.md`. 그 이전 07-26~30 = 성장 전략 정본(`docs/GROWTH_STRATEGY.md`)·색인 표면 50→2,188건(PR #41)·GitHub Actions CD(PR #42·#43)·IndexNow(PR #43~#45)·계산기 거짓 안전판정 수습(PR #37).)

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
- **리드→가입 전환 훅 + 자격 처방 (2026-07-18 세션2 · PR #27·#28 머지 · 배포 완료 — 이후 7/26~30 다수 배포가 master 를 그대로 반영. 구 문서의 '배포 대기' 표기는 정정됨)** —
  ① **전환 훅**(#27): `services/lead_conversion.py` `link_leads_to_user` — 가입(이메일·소셜 신규) 시 동일 이메일 Lead 를 `converted_user_id`+`nurture_status='converted'` 기록. 이메일 정규화(소문자·trim) 조회 시점 매칭(양쪽 저장 정규화 없음), 동일 이메일 다건 전부 전환(사용자 승인), best-effort 이중 가드(가입 절대 안 막음). 어드민 `GET /admin/leads/stats`(총/전환율/업종/일별/최근). 스키마 변경 없음(컬럼 기존 마이그에 존재). 부수: `test_ai_analysis` 리미터 teardown 누수(enabled=True 복구 → 뒤 테스트 429) 수정.
  ② **자격 처방**(#28, 안전망 ③): `QualificationChecker`에 `prescriptions`(requirement/issue/action/confidence) 추가 — **데이터 있는 요건만**(지역 확정·면허 "공고명 추정" 명시·프로필), 실적·시공능력은 공고 기준액 부재로 처방 안 함(후속 파이프라인). **프로필 미기재 = FAIL→UNKNOWN(판정 불가) 정직화**(사용자 승인, 추천배치·진단은 PASS만 봐서 행동 불변). `details` 문자열·뱃지 하위 호환 유지(5개 호출처 무변경). ai.py tip 처방 연동+ℹ️ UNKNOWN, bid.html "이렇게 하면 참여할 수 있어요" 블록. 디마 연 99만원 적격진단의 기본 제공 언더컷. 총 378건 통과.

- **성장 전략 정본 + 유입 인프라 (2026-07-26~30 · PR #41~#45 머지·배포·라이브 검증 완료)** — 상세 문서: `docs/GROWTH_STRATEGY.md`(정본)·`docs/DEPLOY_CD.md`(CD)·`docs/SEO_CHECKLIST.md` §C-2(IndexNow)·`docs/OUTBOUND_SETUP.md`(SES·알림톡).
  ① **색인 표면 개통**(#41): `/sitemap.xml` 이 정적 6개 + 블로그만 담아 **공고 URL 이 사실상 0**이던 문제 → 사이트맵 **인덱스**로 전환(`/sitemap-static.xml`·`/sitemap-blog.xml`·`/sitemap-notices-{N}.xml`, `SITEMAP_CHUNK=5000`). `/search` 를 **SSR**(마감순 40건 `<a href="/bid/...">`)로 만들어 크롤러 진입 경로 개통 — JS 가 로드되면 교체하므로 사용자 UX 불변. 미해결 공고 상세는 200 대신 **404** 반환(soft-404 제거). nginx `/search`·`/sitemap-*.xml` 프록시 추가, `search.html` → `backend/templates/search.html` 이동(git rename). 실측 **2,188건**.
  ② **GitHub Actions CD**(#42·#43): `.github/workflows/deploy.yml` — `workflow_dispatch` 전용(자동 배포 아님), master SHA 의 `test`+`build` check-run 이 `completed:success` 여야 진행(**우회 플래그 없음**), known_hosts 핀 고정, 배포 후 `/health`(`status:ok`·`database:connected`)·`bideasy.kr`·`sitemap.xml` 검증. 서버는 `~/deploy-agent.sh` **forced command**(레포 밖 경로 — 배포가 화이트리스트 자체를 바꾸지 못하게)로 `deploy|indexnow-backfill|status|health` 만 허용, 그 외·인자·`;` 혼입 전부 거부. **`.env.production` 열람·임의 셸 차단 라이브 검증 완료.**
  ③ **IndexNow 통보**(#43·#44·#45): `services/indexnow.py` — 네이버 서치어드바이저 + api.indexnow.org. **운영 전용**(`APP_ENV=production` + 키 설정 시에만 — dev/test 가 실제 엔진에 쏘지 않게), 회당 상한 `MAX_PER_RUN=2000`(자동 훅 폭주 방어) + 일괄 통보만 `max_urls` 로 override, 자기 호스트 필터·중복 제거, **예외 절대 미전파**(통보 실패가 발행·수집을 되돌리지 않음). 훅: `crawl_daily` 신규 공고·블로그 발행(태스크·어드민). 키는 **비밀이 아님**(프로토콜상 `/{key}.txt` 공개 필수) — config 기본값과 키 파일 일치를 테스트가 강제. 일괄 2,199건 통보 완료.
  ⚠️ 정직: 이건 **통보이지 색인 보장이 아니다.** 효과는 서치콘솔·서치어드바이저 수집 현황으로 2주 뒤 사후 판정. 킬 기준은 `GROWTH_STRATEGY.md` §7 에 사전 등록됨.

- **아웃바운드 이메일 — 동의 증적 + SES 발송 파이프라인 (2026-07-30 · PR #47 머지·배포·실발송 검증 완료)** — 운영 런북 `docs/OUTBOUND_EMAIL.md`, 퍼널 맥락 `docs/LEAD_ACQUISITION.md` §3-1·§3-2.
  ① **동의 증적이 먼저**(마이그 `f4c1e8a92b37`): 정보통신망법 §50 은 수신동의 사실의 **증명책임을 전송자**에게 지운다 → 증적 없이 발송을 붙이면 SES 승인이 나도 못 쓴다. `consent_records`(추가 전용·수정삭제 API 없음·대상 삭제돼도 남도록 FK 없이 연락처 스냅샷) + `Lead`/`User` 상태 컬럼 + 문구 정본(버전별 영구 보존·본문 sha256). `/diagnose`·`/signup` 은 **사전 체크 없는** 명시 동의 UI, 캐시된 구버전 페이지 제출은 증적이 없어 자동 제외.
  ② **발송 판정을 한 곳에 고정**: `services/consent.py` `can_send_marketing`(단건)/`sendable_filter`(쿼리) — 동의·철회·**2년 재확인**(§50⑧)을 함께 본다. 발송 코드가 `marketing_consent == True` 만 보고 자체 판단하면 사고.
  ③ **발송 파이프라인**(마이그 `a9d3f5c17e42`): `services/nurture.py` **유일 진입점**(게이트→멱등 선점→렌더→전송→원장), `mailer.py`(SES `send_raw_email` — `SendEmail` 로는 `List-Unsubscribe` 헤더 불가), `email_templates.py`(공통 조립기가 "(광고)" 접두·발신자·수신거부를 **강제** → 새 템플릿이 법정 표기를 빠뜨릴 수 없음), `OutboundMessage` 원장(`dedupe_key` 유니크, **차단된 건도** `no_consent`·`no_email`·`duplicate` 로 기록).
  ④ **수신거부**: 용도 한정 HMAC 서명 토큰(`core/signed_token.py`, **만료 없음** — 언제든 철회 가능이 법 취지, 노출돼도 가능한 일은 해지뿐). `GET /unsubscribe/status`(조회) / `POST /unsubscribe`(처리·RFC 8058 원클릭) 분리 = 메일 스캐너 프리페치로 인한 오해지 방지. 정적 페이지 `/unsubscribe`.
  ⑤ **운영 가동**: 발송 전용 IAM `bideasy-ses-sender`(+인라인 정책 `BideasySesSendOnly` = `ses:SendRawEmail`·`SendEmail`, 서울 리전 한정) 신규 생성 → 서버 `.env.production` 에 `OUTBOUND_EMAIL_ENABLED=true`·`AWS_ACCESS_KEY_ID`·`AWS_SECRET_ACCESS_KEY` 3줄 추가(백업 `~/env.production.bak-20260730-outbound`) → 재배포. **라이브 실증**: 거래 템플릿 실제 1통 `sent`(CloudWatch Send 1·Delivery 1·Bounce 0·Complaint 0), 미동의 광고메일 `skipped/no_consent`, 서명 토큰 정상 200·변조 400. 어드민 `/admin/consents`·`/consents/summary`·`/admin/outbound`·`/preview`·`/test-send`.
  ⚠️ **기존 리드·회원은 전부 미동의로 시작**(마이그 기본값 false) — 2026-07-30 이전 캡처분에 광고성 메일 **소급 발송 금지**.

- **리드 육성 시퀀스 — 더블 옵트인 (2026-08-01 · PR #50 머지·배포·E2E 실검증 완료)** — 상세·설계 판단 5가지 = `docs/LEAD_ACQUISITION.md` §3-3.
  진단 캡처 → `lead_optin_confirm`(**거래**, 광고 미포함) → 확인 클릭 → `lead_welcome`(광고) → 매주 화 08:00 `lead_new_matches`(광고).
  ① **자격 판정 단일 소스** `services/lead_matching.py` — 진단 화면이 "50건"이라 보여준 뒤 메일이 다른 기준으로 고르면 판정 신뢰가 깨진다. `since` 로 신규만 볼 수 있고, 콜드-DB 워밍은 진단 화면 전용 관심사라 `leads.py` 에 남겼다.
  ② **더블 옵트인** — `/leads/capture` 는 인증도 주소 소유 확인도 없는 공개 폼이다. 본문의 `marketing_consent:true` 만 믿고 보내면 남의 주소를 적은 요청이 그대로 **제3자 광고**가 된다(증적은 제출자 IP·UA 일 뿐). `grant_marketing(confirmed=False)` → `marketing_confirmed_at` NULL → `sendable_filter` 차단. 확정은 `POST /leads/optin` 으로만(GET 은 조회 — 메일 스캐너 프리페치가 대신 누르는 것 방지). 정적 `/optin`, `confirm_pending` 을 보고 `/diagnose` 가 안내.
  ③ **멱등 주체 = 수신자**(이메일 sha1) — 캡처는 upsert 없이 매번 새 `Lead` 행을 만들어, 행 기준 키는 재진단·더블클릭마다 갈라진다. 배치도 수신자당 1건만 뽑는다.
  ④ **`can_send_marketing` 폴백 제거** — `marketing_confirmed_at` 이 없을 때 `marketing_consent_at` 으로 폴백하던 것을 없앴다. 폴백이 있으면 확인 대기가 발송 가능으로 새고, SQL 판본(`sendable_filter`)과 판정이 갈라진다.
  ⑤ **실패는 1건에 갇힌다** — 입력 제어문자 정제(공백 치환) + `mailer` 가 조립 실패도 `MailerError` 로 변환 + 배치 리드 단위 `except` + 실패 시 `dedupe_key` 해제(선점만 하고 멈춘 `sending` 유령행이 재발송을 영구히 막지 않게).
  **E2E 실측(2026-08-01)**: 캡처 `confirm_pending=true`·광고 미발송 → 확인 메일 수신 → 클릭 → `(광고)` 웰컴 수신·수신거부 링크·발신자 표기 정상. 운영 첫 리드 `lead_id=1`.
  ⚠️ 주간 배치(`nurture.send_lead_matches`)는 **아직 한 번도 안 돌았다** — 2026-08-04 화 08:00 첫 발동으로 beat 등록을 실증한다.

### ⏳ 대기 중인 외부 작업 (코드 아님, 사용자/제3자 처리)
| 항목 | 상태 |
|---|---|
| **AWS SES** | ✅ **완전 가동**(2026-07-30). 프로덕션 승인 GRANTED(50,000통/일·14통/초, ap-northeast-2) + 도메인 Verified·DKIM 3종 SUCCESS·SPF·DMARC + **발송 전용 IAM `bideasy-ses-sender`** + 서버 env 설정 + **실발송 1통 성공**(Delivery 1·Bounce 0). 남은 건 코드(반송 억제·시퀀스) |
| **루트 액세스 키 폐기** | 🚨 **미완 — 우선 처리**. 루트 액세스 키는 MFA 로도 제한 못 하는 전권이라 존재 자체가 위험. 콘솔 → 보안 자격 증명에서 폐기. **절차 = `docs/SECRET_ROTATION.md` §3-1.** ⚠️ 2026-08-01 정정: `[default]` 사본은 **구 PC(t14s) 기준**이고 현 PC(x1)에는 `[bideasy]` 프로필만 있으며 aws CLI 도 미설치 — 즉 로컬 조치는 불필요하고 **계정 차원의 폐기**만 남았다 |
| **`CONTENT_LLM_*` 미설정** | ⚠️ 서버 `.env.production` 에 `CONTENT_LLM_MODEL/BASE_URL/API_KEY` 가 **없다**(2026-07-30 실측). 즉 블로그 정본이 Sonnet 5(OpenRouter)가 아니라 기본값 `gpt-4o`(OpenAI 직결)로 생성돼 왔을 가능성 — CLAUDE.md 구버전의 "적용 완료" 기술과 불일치. 다음 세션에서 확인·설정 |
| **카카오 알림톡** | ❌ 채널 없음(2026-07-29 확인) → 개설 필요. **리드타임 2~3주**(일반 채널 즉시 → 비즈니스 채널 전환 3~5일 → 발신프로필 심사 영업일 최대 10일 → 템플릿 심사 2~3일). 그래서 **이메일이 먼저**, 알림톡은 마감·매칭 알림용 후행 |
| **Google Search Console** | 사이트맵 재제출(30초, 선택 — robots.txt 로도 발견됨) |
| **토스 MID 심사** | 진행 중 — 페이플 운영 라이브(6/17)로 긴급성 낮음, 병행 가능 |
| **Chrome 웹스토어** | ASO 개정판 검토 제출(6/20). ⚠️ **listing 가격 문구 24,900→19,900 갱신 필요**(런칭 기념가). 툴바 아이콘 `npm run build` + 재제출 대기 |
| **익스텐션 코드 정리** | `plan→tier` 파라미터 정리 + 포인트 버튼 처리 → 다음 재제출에 포함. **지금은 웹 checkout이 흡수해 급하지 않음** |
| **익스텐션 A값 Tier1 활성화** | 웹스토어 승인 후 |
| **OpenAI 키·POSTGRES_PASSWORD 로테이션** | ⚠️ 미완 — 6/19 감사에서 노출 확인, 사용자 처리 필요. **절차 = `docs/SECRET_ROTATION.md` §3-2·§3-3** (Postgres 는 `.env` 만 고치면 안 되고 DB 안에서 `ALTER USER` 가 먼저다 — 흔한 사고). ⛔ 같은 문서 §4: `BILLING_ENC_KEY` 는 **로테이션 대상이 아니다** |

### 2차 = 고객 검증 (GTM 진행 중 — 상세: 메모리 `bideasy-gtm-strategy`)
- **비치헤드 확정** (2026-07-07): 전문건설(전기공사 먼저) 1~10인, **월 10건+ 직접 투찰**(빈도 기준). 훅=자격필터 / 지갑=안전 투찰. 물품은 하한선 없어 안전게임 아님(제외).
- **검증기계(전화 0통)**: 네이버 검색광고 A/B(안전 vs 자격필터 훅) — 캠페인 패키지 완성, **집행 보류 중** → `docs/AD_CAMPAIGN_VALIDATION.md`. 측정 = first-touch UTM + GA4 + `/admin/stats/attribution`.
- **census 전수조사 = 하지 않음** — 공사 개찰 169k행/일이라 전수는 함정. sample≈census는 통계로 보장. (개찰 API: window ≤24h·시작도 실제시각·num_rows 작게. 코드 `3/5/1`=공사/용역/물품.)
- 남은 검증 코드: 가입 직후 1문항 마이크로 설문(업종·월 투찰수) + 커뮤니티 질문글.

### 다음 주제
- **주간 매칭 배치 첫 발동 확인 (2026-08-04 화 08:00 KST)** — `nurture.send_lead_matches` 가 실제로 도는지 = beat 스케줄이 등록됐는지의 유일한 실증. E2E 로 만든 **`lead_id=1`(hosicompany@gmail.com)이 그대로 대상**이라 메일이 오면 성공. 안 오면 `celery_beat` 스케줄 등록을 의심(`deploy.sh` 가 force-recreate 하도록 돼 있으나 실측은 아직). 확인처 = `/admin/outbound` 원장. 그 뒤 수신거부 링크까지 눌러보면 전 구간이 닫힌다.
- **웰컴 메일 캡 표기 (작음)** — `lead_welcome` 은 `matched_count` 를 그대로 말하는데 이 값은 `MATCH_LIMIT=50` 에 걸린 값이라 실제로는 더 많다. `lead_new_matches` 는 `capped` 로 "50건+" 을 쓰고 진단 화면도 `capped` 를 쓰는데 웰컴만 빠져 있다 — 정직·비예측 포지션과 어긋난다.
- **체험 라이프사이클 시퀀스 6통** — D0/D1/D3/D7/D11/D13(`GROWTH_STRATEGY.md` §C3). **광고/거래 구분해 템플릿 배치**: 체험 만료 고지는 거래(동의 불요), 할인·권유는 광고(동의 필요). 섞으면 메일 전체가 광고물이 된다.
- **수신거부 처리 결과 통지** — 정보통신망법상 철회 처리 결과를 통지해야 한다(현재 즉시 반영은 되나 통지 메일은 미구현).
- **카카오 알림톡 채널 개설** — 리드타임 2~3주(사용자 대기). 게이트(`consent.py`)는 그대로 재사용하고 어댑터만 추가.
- **랜딩 미니계산기 슬라이더 범위** (작음, PR #37 잔여) — `index.html` `DEMO_MIN/MAX = 86.5/90.5` → 계산기 본페이지처럼 `85/92` 로. 현재 하한 89.745% 에서 안전 구간이 0.755%p 뿐이라 게이지가 거의 빨강 = 첫인상 손해.
- **유입 효과 판정 (2주 뒤 = 2026-08-13 경)** — 서치콘솔 색인 페이지 수·서치어드바이저 수집 현황·GA4 오가닉 세션. 판정 기준·킬 기준은 `docs/GROWTH_STRATEGY.md` §7 에 **사전 등록**돼 있음(사후 합리화 금지).
- **익스텐션 재제출** — `plan→tier` 정리 + 포인트 버튼 + 툴바 아이콘 빌드 + **오버레이 진단 CTA**(리드 마그넷 연동) → Chrome 웹스토어 재제출 (listing 가격 문구도 19,900 갱신).
- **랜딩 개편 효과 측정** — GA4에서 `cta_*`·`calc_demo_use`·`lead_diagnose`·`lead_capture` 전환율 관찰. 데이터 보고 개선 반영.
- **랜딩 A/B 훅 실험** — 안전 vs 자격필터 훅 A/B는 **미착수**(광고 검증 캠페인과 연동, 현재 집행 보류). 이번 랜딩 개편은 전환 구조까지만 완료.
- ~~**CI green 복구**~~ → **해소됨**(2026-07-30 실측: `test`·`build`·`lint`·`flutter` 4종 모두 green). 이전 문서의 "lint 25개 오류·상시 red" 기술은 더 이상 사실이 아니다.

### 이후 (고객 검증 통과 후, 선착수 금지)
- 자가학습 안전비서 Phase1(`UserBid`↔`OpeningResult` 피드백 루프)
- Pro+ ML 웹 노출, 웹푸시(FCM), 윈백 이메일 인프라(SES — 이탈자는 앱내 알림으로 안 닿음)
- (6/22) UTM 마이그레이션 배포·마케팅 링크 UTM 태깅·Cloudflare Web Analytics — 완료 여부 확인 필요

> 세션 루틴: 새 세션 `/kickoff` → 작업 → `/handoff` (전역 슬래시 명령, 2026-07-07 신설).

---

## ⚠️ 함정·금지 목록 (필독 — 위반 시 운영 사고)

1. **`BILLING_ENC_KEY` 변경·재생성 절대 금지** — 변경/분실 시 암호화된 빌링키 전부 복호화 불가(고객 전원 재카드등록). `infra/.env.production`에만 존재, 안전 백업 필수.
2. **KPI·마케팅에 '낙찰률' 사용 금지** — 개찰데이터 검증 결과 승률 지표는 과적합(8%→23%) + 사정률 추첨은 랜덤. 핵심 지표 = 유효율 95% + 입찰당 재사용률.
3. ~~**`deploy.sh`가 안 하는 것**: `celery_beat` 재생성 안 함~~ → **해소됨(PR #39·#40)**. 이제 `./deploy.sh deploy` 가 `celery_beat` 를 force-recreate 하고 기동 실패 시 배포를 실패로 종료한다. 또 `deploy.sh` 자신이 바뀌면 pull 된 새 스크립트로 `exec` 재시작한다. **수동 재생성 안내는 폐기** — 다른 문서에 남아 있으면 정정할 것.
4. **config fail-fast**: `APP_ENV=production`에서 `JWT_SECRET_KEY` 미설정 또는 `POSTGRES_PASSWORD=bideasy_pass`(기본값)면 앱 기동 실패.
5. **비-root 컨테이너(uid 10001)**: named 볼륨(`infra_strategy_data`·`infra_celerybeat_data`)이 root 소유면 백그라운드 워커 쓰기 실패. 최초 1회 `docker run --rm -v <볼륨>:/d alpine chown -R 10001:10001 /d`.
6. **헬스체크 10초 오탐**: deploy.sh는 app 재생성 10초 뒤 체크 → `WARNING: Health check failed`는 대개 오탐. 진짜 상태는 `https://api.bideasy.kr/health`(200 + `database:connected`).
7. **app 수동 재생성 시 nginx reload 필수** — 도커 IP가 바뀌어 nginx가 옛 IP로 502. `./deploy.sh deploy`는 자동 처리(수동 compose up 시 누락 주의).
8. **페이플 콜백 리다이렉트는 303** (307이면 정적 `/account`에 POST 재전송 → nginx 405).
9. **버전 표기**: 현재 v1.2 (2026-07-08 랜딩 개편 시 v1.1→v1.2) — 변경 성격(MAJOR/MINOR/PATCH)을 판단해 랜딩 푸터에 반영.
10. **이메일 발송은 `services/nurture.py` 경유만** — `mailer.send()` 직접 호출 금지(동의 게이트·원장 우회). 광고성은 `send_marketing`, 거래 고지는 `send_transactional`. **거래 메일에 할인·권유 문구를 끼우면 그 메일 전체가 광고물**이 되어 동의 없이 보낸 위법 발송이 된다.
11. **동의 없는 연락처에 광고 발송 금지 — 소급 동의도 금지.** 2026-07-30 이전 리드는 증적이 없다. 발송 대상은 반드시 `can_send_marketing`/`sendable_filter` 통과분만. 문구를 고칠 때는 **새 버전 키를 추가**(기존 삭제 금지)하고 화면 `data-consent-version` 도 함께 올린다(`tests/test_consent.py::TestConsentTextDrift` 가 감시).
12. **`OUTBOUND_EMAIL_ENABLED` 를 임의로 끄지 말 것** — 현재 true(라이브). 끄면 모든 발송이 조용히 `dry_run` 이 되어 "보낸 줄 알았는데 안 감" 사고가 난다. 반대로 켠 채 대량 시퀀스를 돌리기 전에는 **반송·불만 억제**(§다음 주제)가 먼저다 — 반송률 5%·불만율 0.1% 초과 시 AWS 계정 정지.
13. **`dedupe_key` 없이 주기 발송 금지** — 규칙은 **수신자 기준** `"{template}:email:{sha1(이메일)}[:{주기}]"`. `lead.id` 로 잡지 말 것 — `/leads/capture` 는 upsert 없이 매번 새 `Lead` 행을 만들어서, 같은 사람이 재진단·더블클릭하면 키가 갈라져 같은 메일이 여러 통 나간다.
14. **`can_send_marketing` 에 폴백을 되살리지 말 것** — `marketing_confirmed_at` **만** 본다. `marketing_consent_at` 으로 폴백하면 ① 더블 옵트인 확인 대기가 발송 가능으로 새고 ② SQL 판본 `sendable_filter`(이 컬럼 필수)와 판정이 갈라진다. 판정이 두 갈래면 언젠가 위법 발송 쪽으로 갈라진다.
15. **리드에게 보내는 첫 메일은 광고가 될 수 없다** — `/leads/capture` 는 인증·주소 소유 확인이 없는 공개 폼이다. 캡처 직후 나가는 건 `lead_optin_confirm`(거래·광고 미포함)뿐이고, 광고는 **확인 클릭 이후**에만. 확인은 `POST /leads/optin` 으로만 처리한다(GET 으로 확정하면 메일 스캐너 프리페치가 사용자 대신 눌러 더블 옵트인이 무의미해진다 — 수신거부와 같은 규칙).
16. **발송 배치는 리드 단위로 예외를 가둘 것** — 데이터 결함 1건(제목에 섞인 개행 등)이 배치를 끊으면 매주 같은 지점에서 전원이 조용히 메일을 못 받는다(beat 는 실패를 알리지 않는다). 실패는 원장에 `failed` + **`dedupe_key` 를 놓은 상태**로 남아야 재시도가 가능하다.

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
>
> 💡 **레포 4개를 한 창에서 보려면** `bideasy.code-workspace` 를 여세요 (VS Code/Cursor). 4개가 `C:\dev\bideasy-suite\` 아래 **형제 폴더**로 있는 것을 전제로 상대경로 참조합니다 — 폴더를 옮기면 이 파일의 `path` 도 함께 고치세요.
>
> 📂 **작업 루트 = `C:\dev\`** (2026-08-01 통합). BidEasy 4종은 `C:\dev\bideasy-suite\`, 다른 개발 프로젝트는 `C:\dev\` 직하. Claude Code 는 반드시 **`C:\dev\bideasy-suite\Bideasy`** 에서 실행해야 메모리가 붙습니다(프로젝트 키 `C--dev-bideasy-suite-Bideasy`).

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
| `leads.py` | 무료 자격 진단 리드(`/leads/diagnose`·`/capture`·`/consent-texts`) — 공개·IP 레이트리밋, 캡처 시 **동의 증적 기록** |
| `unsubscribe.py` | **수신거부**(공개·무인증) — `GET /unsubscribe/status`(조회) · `POST /unsubscribe`(처리·RFC 8058 원클릭). 서명 토큰 |
| `health.py` | `/health` |
| `admin/*` | 관리자 전용 (`require_admin` 가드). 아웃바운드 관련: `consents.py`(증적 검색·발송가능 규모)·`outbound.py`(발송 원장·미리보기·테스트 발송) |

---

## 5. 서비스 & Celery 스케줄

**핵심 서비스** (`backend/app/services/`):
- `calculator.py` — 투찰가 계산(핵심). `crawler.py` — 멀티카테고리(공사/용역/물품) fan-out 수집.
- `billing.py`(토스) / **`payple.py`(페이플)** — 빌링키 발급·청구. `payments_refund.py` — 환불.
- `qualification_checker.py` — 자격 판정(PASS/FAIL + 뱃지). `attachment_avalue.py` — A값 Tier2(첨부 HWP/PDF 파싱).
- `bid_detail.py` — 단건조회(inqryDiv=2 + 멀티카테고리). `opening_result*.py` — 개찰결과 누적.
- **아웃바운드**: `consent.py`(동의 문구 정본·증적·**발송 판정 단일 소스**) → `nurture.py`(**유일 발송 진입점**: 게이트→멱등→렌더→전송→원장) → `email_templates.py`(법정 표기 강제) → `mailer.py`(SES raw). 상세 런북 `docs/OUTBOUND_EMAIL.md`.
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

## 6-1. 새 컴퓨터 세팅 (개발 환경 재구성)

레포만 clone 하면 **코드·문서·배포 권한 전부** 따라온다. 다음 3개만 추가로 필요:

```bash
git clone https://github.com/hosicompany/Bideasy.git && cd Bideasy
gh auth login                                    # PR·머지·배포 버튼용 (scope: repo, workflow)
pip install -r backend/requirements.txt          # Python 3.12
cd backend && pytest                             # 통과 확인 (기준 §8)
```

- **서버 SSH 키는 필요 없다** — 배포는 GitHub Actions 버튼(§7). 로컬에서 서버에 붙지 않는다.
- **AWS 키**(`~/.aws/credentials` 프로필 `bideasy`)는 SES 관리 작업에만 필요. 새 PC 로 옮기지 말고, 필요할 때 IAM 콘솔에서 새로 발급하는 게 안전하다(구 키는 폐기).
- `backend/bideasy.db`(로컬 SQLite)·`.env` 는 git 에 없다 — 테스트는 in-memory 라 없어도 통과한다.
- ⚠️ 옮기지 말 것: `infra/.env.production`(서버에만), `PATENT.md`·`MORNING_CHECKLIST.md`·`OVERNIGHT_REPORT.md`(§9).

---

## 7. 배포

### 기본 경로 — GitHub Actions 버튼 (SSH 불필요) ★
GitHub → **Actions → Deploy to production → Run workflow**. 또는 세션에서 "배포해줘"라고 하면 대신 눌러준다.
- master 의 `test`+`build` check-run 이 **green 이어야만** 진행(우회 플래그 없음).
- 배포 후 `/health`·`bideasy.kr`·`sitemap.xml` 을 워크플로가 직접 검증 → 실패 시 job red.
- 서버는 `~/deploy-agent.sh` forced command 로 `deploy|indexnow-backfill|status|health` 만 허용. 상세·시크릿·실패 대응표: `docs/DEPLOY_CD.md`.

### 수동 경로 (서버 직접 접속 시)
서버(Lightsail)에서 **백엔드는 Docker 컨테이너**로 구동 → `alembic`은 호스트 PATH에 없음(컨테이너 내부에만).

```bash
# 표준 배포 (코드 pull + 이미지 재빌드 + 롤링 재시작 + 마이그레이션)
cd ~/Bideasy/infra && ./deploy.sh deploy
```
`deploy.sh`가 자동 수행: `git pull origin master` → `dc build app celery_worker` → 롤링 재시작 → 헬스체크 → **`dc exec app alembic upgrade head`**.
- 기타: `./deploy.sh {status|logs|backup|rollback|ssl-init}`. 프로젝트명 `-p infra` 고정.
- 마이그레이션만 수동: `docker compose -f docker-compose.prod.yml --env-file .env.production -p infra exec app alembic upgrade head`
- **현재 마이그레이션 head**: `c8e5b1f37d94` (email_suppressions — 반송·불만 억제). 직전 `a9d3f5c17e42`(outbound_messages 발송 원장) → `f4c1e8a92b37`(수신동의 증적) → `b7e2c4f9a801`(blog blocks) → `d9f3a1b7c204`(leads). *리드 육성(PR #50)은 스키마 변경 0.*

---

## 8. 테스트 — 검증 명령 (코드 변경 후 반드시 실행)

```bash
cd backend && pytest          # 527건 통과 기준 (2026-08-01 master 실측, PR #50 병합분 포함. SQLite in-memory/파일)
python -m ruff check backend/ # CI lint 와 동일 — 미사용 import 하나로 CI 가 red 가 된다
```
- **모든 코드 변경 후 위 명령을 실행하고, 완료 보고(Gate Check)에 결과와 신뢰도(🟢🟡🔴)를 기재한다.** 실패 상태로 커밋·배포 금지. 실패 수정은 2회까지, 이후 에스컬레이션.
- 결제: `tests/test_billing.py`(토스), `tests/test_payple.py`(페이플 9건 — provider/prepare/callback/서비스청구/Celery갱신, HTTP 모킹).
- 아웃바운드: `tests/test_consent.py`(20건 — 증적 기록·구버전 경로·2년 만료·SQL필터↔단건판정 일치·**화면↔서버 문구 드리프트 가드**), `tests/test_nurture.py`(26건 — 게이트 차단 시 실제 미발송·"(광고)" 표기·원클릭 헤더·멱등·실패 시 키 해제·토큰 위조/용도 전용), `tests/test_lead_nurture.py`(19건 — **제3자 주소 광고 차단**·GET 프리페치 무확인·철회자 부활 방지·개행 리드가 배치를 안 죽임·같은 사람 재진단 시 1통).
- 그 외 feed/calculator/qualification/favorites/deadline/ai 등.

---

## 9. 🔒 보안 규칙 (반드시 준수)

1. **비밀키는 코드/git에 절대 없음.** 실값은 **서버 `infra/.env.production`에만** (git 제외). 토스/페이플/PUBLIC_DATA/OPENAI/JWT 키 전부.
   - 단, `config.py`의 페이플 값은 **공개 테스트 샌드박스 기본값**(실 운영키 아님).
   - `JWT_SECRET_KEY`는 `.env.production`에 **고정**해야 함(미설정 시 배포마다 전원 로그아웃).
2. **`PATENT.md` 절대 커밋·푸시 금지** (내부 IP). `.gitignore`에 `**/PATENT.md` 등록됨. `MORNING_CHECKLIST.md`·`OVERNIGHT_REPORT.md`도 동일.
3. **git push는 매번 사용자 명시 승인 후** 실행.
4. 관리자 계정: `hosicompany@gmail.com` (비번은 별도 보관).
4-1. **AWS 자격증명 분리**: 서버(`.env.production`)에는 **발송 전용** `bideasy-ses-sender` 키만 둔다(`ses:SendRawEmail`·`SendEmail`, 서울 리전 한정). 콘솔 관리용 `bideasy-ses-admin`(`ses:*`)을 서버에 두지 말 것. 🚨 로컬 `~/.aws/credentials` `[default]` 는 **루트 계정 키**라 폐기 대상(§대기 항목).
4-2. **서버 SSH**: Lightsail 기본 키페어 개인키를 `~/.ssh/lightsail_bideasy.pem`(600)에 보관(2026-07-30, `aws lightsail download-default-key-pair` 로 취득). 배포는 이 키가 아니라 **GitHub Actions 버튼**(forced command)을 기본 경로로 쓴다 — 이 키는 `.env.production` 편집처럼 자동화가 못 하는 작업용.
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
