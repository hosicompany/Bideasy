# 🔒 BidEasy 보안 감사 보고서

- **감사일:** 2026-06-19
- **감사 범위:** 백엔드(FastAPI, 98파일) · 웹(nginx 정적 + SSR) · 크롬 익스텐션(Manifest V3 / TypeScript) · 인프라/시크릿/git 위생
- **방식:** 영역별 전문 감사 에이전트 5종 병렬 코드 정독 + 핵심 항목 직접 재검증
- **대상 레포:** `C:\Project\Bideasy` (백엔드/웹/인프라), `C:\Project\Bideasy-Extension` (크롬 익스텐션)

---

## 패치 진행 현황 (2026-06-19, 브랜치 `security/audit-2026-06-19`)

| # | 항목 | 상태 |
|---|---|---|
| 1 | 페이플 콜백 검증 + 빌링키 저장 방어 | ✅ 패치 (commit c0d3cac) |
| 2 | SSRF 화이트리스트(url_guard) | ✅ 패치 |
| 3 | 정적 웹 XSS 이스케이프(BD.esc) | ✅ 패치 |
| 4 | OAuth state(CSRF) + 카카오 state | ✅ 패치 |
| 5 | 소셜 미검증 이메일 병합 차단 | ✅ 패치 |
| 6 | 익스텐션 로그인 브릿지 + baseURL + CSP | ✅ 패치 (ext 58ef1ec) |
| 7 | 토큰 무효화(token_version) + URL→fragment | ✅ 패치 |
| 8 | 운영 시크릿 로테이션 | ⚠️ **사용자 작업 필요** (OpenAI 키·DB 비번 재발급) |
| 9 | 페이플 멱등성/금액 대조 | ✅ 패치 (#1 에 포함) |
| 11 | 비인증 고비용 엔드포인트 가드 | ✅ 패치 |
| 13 | nginx 보안헤더 재선언 + server_tokens off | ✅ 패치 |
| 14 | config production fail-fast | ✅ 패치 |
| 16 | 익스텐션 401 폐기/baseURL/CSP | ✅ 패치 |
| 22 | 회원가입 EmailStr + 비번 8자 | ✅ 패치 |
| 10 | 빌링키 at-rest 암호화(Fernet) + 카드 로그 제거 | ✅ 패치 (2차) |
| 12 | AI 일일한도 Redis 이관 + 효과 tier | ✅ 패치 (2차) |
| 15 | 컨테이너 비-root + dev DB 로컬 바인딩 | ✅ 패치 (2차) |
| 17·18 | 앱 레벨 레이트리밋(register/login/social) | ✅ 패치 (2차) |
| 19 | LLM 프롬프트 인젝션 구분자/가드 | ✅ 패치 (2차) |
| 20 | 예외 메시지 일반화 | ✅ 패치 (2차) |
| 21 | nginx /admin noindex + auth 가이드 | ✅ 패치 (2차) |
| 23 | sitemap XML escape + 토스 티어 화이트리스트 | ✅ 패치 (2차) |
| — | 익스텐션 PRIVACY_POLICY 실제 구현 일치 | ✅ 패치 (2차) |
| 8 | 운영 시크릿 로테이션 | ⚠️ **사용자 작업 필요** |

> **전 항목 코드 패치 완료.** 백엔드 테스트 301건 통과, 익스텐션 tsc + vitest 41건 통과.
> **운영 배포 전 확인**: 페이플 콜백(라이브) 샌드박스 점검, 시크릿 로테이션, `alembic upgrade head`(token_version·billing_key 폭 확장), 기존 strategy_data/celerybeat_data 볼륨 `chown 10001`(비-root 전환), 빌링키 암호화 사용 시 `BILLING_ENC_KEY` 설정.

---

## 총평

기본기는 상당히 견고하다 — bcrypt 해싱, admin 이중 가드 + 회귀테스트, IDOR 방어(토큰 기반 `user.id` 필터 일관), Pro 티어 서버측 강제, 토스 결제 server-to-server 재검증, git 시크릿 누출 0건, 익스텐션 권한 최소화(`<all_urls>` 미사용). 그러나 **페이플 결제 경로 · SSRF · 정적 웹 XSS · 토큰 수명 관리**에 실재하는 결함이 있고, 특히 페이플은 **현재 운영 라이브** 상태라 최우선 대응이 필요하다.

> **정정 메모:** 1차 자동 감사에서 "인증 브루트포스 무방비(Critical)"로 보고되었으나, 활성 nginx 설정(`infra/nginx/conf.d/default.conf:68`)에 `/api/v1/auth/`용 `limit_req zone=auth burst=3 nodelay`가 실제 적용되어 있음을 직접 확인. 앱 레벨 데코레이터만 부재하므로 **Medium(심층방어 보강)** 으로 조정함.

---

## 우선순위 요약

| # | 심각도 | 항목 | 위치 |
|---|---|---|---|
| 1 | 🔴 Critical | 페이플 콜백 진위 미검증(서명/CST_ID 없음) + 청구 실패 시 빌링키 저장 | `payments.py:880-936` |
| 2 | 🟠 High | SSRF — 사용자 제어 `notice_url`을 서버가 직접 fetch(`verify=False`, IP필터 없음) | `ai.py:135-346`, `scraper.py:66` |
| 3 | 🟠 High | DOM XSS — 공고 데이터를 `innerHTML`에 무이스케이프 삽입 | `search.html:79-93`, `bid.html:46` |
| 4 | 🟠 High | OAuth `state` 미검증(CSRF) + 카카오 state 부재 | `auth.py:192,260` |
| 5 | 🟠 High | 소셜 미검증 이메일 자동 병합 → 계정 탈취 | `auth.py:42-48` |
| 6 | 🟠 High | 익스텐션 로그인 브릿지 — 페이지 토큰 능동 흡수 + 동일출처 postMessage 신뢰 | `bideasy-login.ts:5-40` |
| 7 | 🟠 High | 7일 무효화 불가 베어러 토큰 + JWT를 URL 쿼리로 전달 | `auth.py:257,304`, `security.py:30` |
| 8 | 🟠 High | 운영 라이브 시크릿이 개발PC 디스크에 평문 상주 | `infra/.env.production.local` |
| 9 | 🟡 Medium | 페이플 콜백 멱등성 부재(중복청구) + 금액 미대조 | `payments.py:915-919` |
| 10 | 🟡 Medium | 빌링키 평문 저장 + 카드정보 로그 노출 | `payments.py:745`, `models.py` |
| 11 | 🟡 Medium | 비인증 고비용 엔드포인트(`/crawl`, `scrape-avalue`, cache DELETE) | `bids.py:176,458`, `ai.py:398` |
| 12 | 🟡 Medium | AI 일일한도 인메모리 → 멀티워커/재시작 우회 | `ai.py:32-71` |
| 13 | 🟡 Medium | nginx 보안헤더가 HTTPS 블록에서 소실(`add_header` 덮어쓰기) | `nginx.conf:36` vs `default.conf:49` |
| 14 | 🟡 Medium | JWT_SECRET_KEY prod fail-fast 부재 + DB비번 하드코딩 기본값 | `config.py:12,33` |
| 15 | 🟡 Medium | 컨테이너 root 실행 + `C_FORCE_ROOT` | `Dockerfile`, `compose.prod.yml:58` |
| 16 | 🟡 Medium | 익스텐션: 토큰 만료/401 처리 없음, baseURL HTTPS 미검증, CSP 미선언 | `auth.ts`, `api.ts:13` |
| 17 | ⚪ Low | 계정 열거(register 응답) | `auth.py:81-86` |
| 18 | ⚪ Low | 앱 레벨 레이트리밋 부재(nginx가 1차 커버) | `core/rate_limit.py` |
| 19 | ⚪ Low | 프롬프트 인젝션 — 공고 본문이 신뢰경계 없이 LLM 투입 | `llm_agent.py:62-65` |
| 20 | ⚪ Low | 예외 메시지 클라이언트 노출 | `bids.py:41,82,198` |
| 21 | ⚪ Low | 정적 admin 패널 인증 게이트 없이 서빙 | `default.conf:148` |
| 22 | ⚪ Low | 약한 회원가입 검증(EmailStr 아님, 비번 길이 미검증) | `schemas/user.py:13-16` |
| 23 | ⚪ Low | sitemap.xml 무이스케이프 + 토스 티어 order_id 파싱 미검증 | `pages.py:117`, `payments.py:366` |

---

## 백엔드 — 인증 · 인가 · 세션

### [Critical→조정 Medium] 인증 엔드포인트 앱 레벨 레이트리밋 부재 (#18)
- `slowapi` `limiter`가 등록(`main.py:46`)됐으나 `@limiter.limit(...)` 데코레이터가 코드 전체에 0건.
- **단, 활성 nginx가 `/api/v1/auth/`에 IP당 레이트리밋 적용 중**이라 1차 방어는 존재. 분산 IP/`X-Forwarded-For` 스푸핑 대비 앱 레벨 보강 권장.
- **조치:** 로그인/회원가입/소셜에 `@limiter.limit("5/minute")` + 실패 누적 backoff.

### [High] OAuth `state` 미검증 (CSRF) + 카카오 state 부재 (#4)
- `auth.py:192`가 `naver_state`를 생성하나 서버에 저장하지 않고, `naver_callback`(`auth.py:260`)이 `state`를 검증하지 않음. 카카오 인가 URL(`auth.py:199`)엔 `state` 자체가 없음.
- **공격:** OAuth 로그인 CSRF — 공격자 인가 코드를 피해자 브라우저로 콜백시켜 계정 묶기/세션 고정.
- **조치:** `state`를 Redis(TTL 5분)에 저장 후 콜백에서 일치 검증, 카카오에도 추가.

### [High] 소셜 미검증 이메일 자동 병합 → 계정 탈취 (#5)
- `_find_or_create_social_user`(`auth.py:42-48`)가 소셜 식별자 미스 시 **이메일만으로** 기존 계정을 찾아 소셜 정보를 덧씌움. 공급자 이메일 검증 여부(`is_email_verified`)를 확인하지 않음.
- **공격:** 공격자가 피해자 이메일을 자기 소셜 계정에 설정 → 피해자의 기존 계정(포인트·결제·빌링키)에 소셜 경로로 진입.
- **조치:** 병합 시 공급자 이메일 검증 플래그 확인, 미검증이면 병합 금지.

### [High] 토큰 무효화 부재 + URL 쿼리 전달 (#7)
- 액세스 토큰만 발급(7일 만료), refresh/logout/blacklist/`jti`/`token_version` 전부 없음(`security.py:30`).
- 소셜 콜백이 JWT를 `RedirectResponse(f"{FRONTEND_URL}/?token={jwt}")`로 전달(`auth.py:257,304`) → 브라우저 히스토리/Referer/액세스로그에 평문 기록.
- **조치:** `User.token_version` 클레임 추가(비번 변경/로그아웃 시 증가), 토큰을 fragment(`#token=`) 또는 일회성 코드로 교환, 만료 단축.

### [Medium] JWT_SECRET_KEY fallback / 회원가입 검증 / AI 한도 (#14,#22,#12)
- `config.py:12` 시크릿 미설정 시 프로세스마다 랜덤 생성 → prod fail-fast 부재(멀티워커 토큰 검증 깨짐).
- `schemas/user.py:13` 회원가입 `email: str`(EmailStr 아님), 비밀번호 길이/복잡도 미검증(변경은 8자 강제 — 정책 불일치).
- `ai.py:32` Free 일일한도가 인메모리 dict → 멀티워커/재시작 우회.

### [Low] 계정 열거 (#17)
- `/register`가 중복 이메일에 `"이미 등록된 이메일입니다"` 400 반환 → 가입 여부 전수 확인 가능(로그인은 통합 메시지로 안전).

### ✅ 확인됨 (안전)
- alg 화이트리스트(HS256) 고정 → `alg=none` 우회 차단 (`security.py:47,82`)
- `exp` 클레임 + 만료 검증, bcrypt 해싱 + salt, 로그인 통합 오류 메시지
- admin 라우터 이중 `require_admin` + 회귀테스트(`test_admin_auth.py`)
- IDOR 방어: favorite/track/payment/points/profile 전부 토큰 `current_user.id`로 필터
- 티어 서버측 강제(`require_tier`), `UserUpdate`에 `tier/is_admin/points` 미포함(권한 자가상승 불가)

---

## 백엔드 — 결제 · 구독

### [Critical] 페이플 콜백 진위 미검증 + 청구 실패 시 빌링키 저장 (#1) ★운영 라이브
- `/payple/callback`(`payments.py:880`)은 인증 없는 공개 엔드포인트. 콜백 진위(페이플 결과 server-to-server 재조회 / `PCD_CST_ID` 매칭 / 서명)를 전혀 검증하지 않고 `PCD_PAY_RST=success`·`PCD_PAYER_ID`를 신뢰.
- 토스 경로는 Confirm API 재검증(`payments.py:119,336`)을 하나 페이플만 이 신뢰 경계가 비어 있음.
- **부분 완화:** 직후 `charge_billing`(파트너 인증) 서버 청구 성공 시에만 구독 활성화 → "공짜 Pro" 직접 불가.
- **잔존 위험:** `payments.py:925` — 청구 실패 시에도 공격자 제어 `payer_id`를 `user.billing_key`에 저장 → 이후 Celery 갱신이 그 빌링키로 청구 시도(오염).
- **조치:** OID 기준 페이플 결과 server-to-server 재조회 + `PCD_CST_ID` 검증 + 금액(`PCD_PAY_TOTAL`) 대조, **청구 성공 전 `billing_key` 저장 금지**, `CONFIRMED` 멱등 가드.

### [Medium] 페이플 콜백 멱등성 부재 + 금액 미대조 (#9)
- 콜백 재전송 시 매번 새 `charge_oid` 생성(`payments.py:915`) → 중복청구 가능. 토스에 있는 `CONFIRMED` 가드가 페이플엔 없음.
- 콜백의 `PCD_PAY_TOTAL`을 `order.amount`와 대조하지 않음.

### [Medium] 빌링키 평문 저장 + 카드정보 로그 노출 (#10)
- `billing_success` 로그에 `card={user.billing_card}` 출력(`payments.py:745`).
- `billing_key`/`PCD_PAYER_ID`가 DB 평문 저장 → DB 유출 시 타인 카드 청구.
- **조치:** 빌링키 at-rest 암호화, 로그에서 카드/빌링키 필드 제거.

### ✅ 확인됨 (안전)
- 토스 콜백 server-to-server Confirm 재검증 + 금액 대조 + idempotency
- 가격은 서버 상수(`subscription.py`)에서만 산출 — 클라 금액 조작 불가
- 포인트 충전 금액 화이트리스트, 환불은 `require_admin` 전용
- 재체험 차단(`trial_started_at`), win-back 1회성(서버 계산), 카드번호 마스킹

---

## 백엔드 — 웹 취약점 / nginx

### [High] SSRF — 사용자 제어 URL 서버 fetch (#2)
- `GET /api/v1/ai/{bid_no}/analysis`가 `notice_url`/`attachment_url`을 쿼리로 직접 수신(`ai.py:135,139`) → `target_url`로 사용(`ai.py:339`) → `ScraperService.fetch_page_content`(`scraper.py:60-76`)가 `url.startswith("http")`만 검사, `verify=False` + 리다이렉트 추종.
- **공격:** `notice_url=http://169.254.169.254/latest/meta-data/...` → 클라우드 메타데이터/내부망 접근.
- 부차: `attachment_avalue.py:42`도 동일 무검증 fetch(현재 DB 출처라 위험 낮음).
- **조치:** fetch 대상을 DB Notice 레코드에서만 도출, 조달청 도메인 화이트리스트, 사설/링크로컬 대역 차단, `allow_redirects=False`.

### [High] DOM XSS — 무이스케이프 innerHTML (#3)
- `search.html:79-93`(`card()`의 `n.title/n.agency/n.region`), `bid.html:46`(`'<h1>' + bid.title`)가 조달청 OpenAPI 데이터를 이스케이프 없이 `innerHTML`에 삽입.
- **공격:** 공고 제목 `<img src=x onerror=...>` → 방문자 전원 스크립트 실행 → `localStorage` JWT 탈취.
- (SSR `bid_detail.html`은 Jinja2 autoescape로 안전 — 정적 HTML만 누락)
- **조치:** `textContent` 또는 HTML 이스케이프 헬퍼.

### [Medium] 비인증 고비용 엔드포인트 (#11)
- `POST /api/v1/bids/crawl`(`bids.py:176`, 인증 없음 — 크롤 fan-out 무한 호출), `GET /{bid_no}/scrape-avalue`(`bids.py:458`, 첨부 다운로드+파싱), `DELETE /ai/{bid_no}/analysis/cache`(`ai.py:398`, 재분석 비용 유발) 모두 비인증.
- **조치:** `/crawl`·캐시 DELETE는 `require_admin`, `scrape-avalue`는 `get_current_user` + 레이트리밋.

### [Medium] nginx 보안헤더 HTTPS 블록 소실 (#13)
- 보안헤더가 `http` 블록(`nginx.conf:36`)에 있으나 HTTPS `server` 블록(`default.conf:49`)이 자체 `add_header`(HSTS)를 선언 → nginx 규칙상 상위 `add_header` 전부 무효화. 실제 응답에 X-Frame-Options 등 누락.
- `server_tokens off;` 부재로 버전 노출.
- **조치:** HTTPS server 블록에 보안헤더 전부 재선언(또는 `snippets/security-headers.conf` include), `server_tokens off;` 추가.

### [Low] 프롬프트 인젝션 / 예외 노출 / sitemap·티어 파싱 (#19,#20,#23)
- `llm_agent.py:62` 공고 본문이 구분자 없이 LLM 투입(출력 JSON 제한·이스케이프되어 영향 제한적).
- `bids.py:41,82,198` `detail=str(e)`로 내부 예외 노출.
- `pages.py:117` sitemap f-string 무이스케이프, `payments.py:366` 토스 티어 order_id 파싱 시 화이트리스트 미검증.

### ✅ 확인됨 (안전)
- SQL 인젝션: ORM 파라미터 바인딩 일관, `text()`는 정적 쿼리만
- CORS: 와일드카드+credentials 조합 없음, 명시적 origin
- 경로 탐색: 파일 경로에 사용자 입력 미사용, `tempfile` 사용
- prod에서 `/docs` 비활성, dotfile(`/\.`) 차단, 디렉토리 리스팅 off

---

## 크롬 익스텐션 (Manifest V3)

### [High] 로그인 브릿지 토큰 능동 흡수 + 동일출처 postMessage 신뢰 (#6)
- `bideasy-login.ts:5-13`가 페이지 `localStorage`/`cookie`에서 토큰을 능동 수집(`tryAutoCapture`, 2초 후 자동), `bideasy-login.ts:20-40`이 `event.origin === location.origin`만으로 `BIDEASY_TOKEN` postMessage를 신뢰.
- **공격:** bideasy.kr에 저장형 XSS/서드파티 침해 시 `window.postMessage({type:'BIDEASY_TOKEN', token:'<위조JWT>'}, location.origin)` 한 줄로 익스텐션에 임의 JWT 주입(origin===self라 통과).
- cookie 토큰 읽기 가능 = 백엔드가 비-HttpOnly 쿠키 발급 가능성.
- **조치:** 능동 흡수 대신 1회성 nonce + 명시적 사용자 액션으로 핸드오프, postMessage에 사전공유 nonce 검증, `matches`를 콜백 경로로 축소, 백엔드 토큰 쿠키 `HttpOnly; Secure; SameSite`.

### [Medium] 토큰 저장/만료, baseURL, CSP (#16)
- `auth.ts:8` JWT를 `chrome.storage.local`에 평문 무기한 저장, `api.ts`에 401 폐기/`exp` 검증 없음.
- `api.ts:13` `setBaseUrl`이 검증 없이 임의 URL 허용 → baseURL 변조 시 JWT가 평문 HTTP로 유출 가능.
- `manifest.config.ts` CSP 미선언(MV3 기본값 의존).
- **조치:** 401 시 `clearToken`+`exp` 사전만료, `setBaseUrl` HTTPS+`*.bideasy.kr` 화이트리스트, `content_security_policy.extension_pages: "script-src 'self'; object-src 'self'"` 명시.

### [Low] all_frames 주입 / 개인정보처리방침 불일치
- g2b 콘텐츠 스크립트 `all_frames: true`(`manifest.config.ts:53`), `RUN_DIAGNOSTIC`이 모든 프레임 텍스트 수집.
- `PRIVACY_POLICY.md`가 PG를 "Toss Payments"로 기재(운영은 payple 전환), "JWT 만료 자동 처리" 문구가 실구현과 불일치, 로그인 브릿지의 토큰 읽기 미명시.

### ✅ 확인됨 (안전)
- 원격 코드 실행/eval/CDN 주입 전무, 실제 DOM은 `createElement`+`textContent`만
- `JWT_RECEIVED` 핸들러 `isTrustedLoginUrl`+`isLikelyJwt` 이중 검증
- `externally_connectable`/`web_accessible_resources` 미선언, `<all_urls>` 미사용, prod baseURL HTTPS, 하드코딩 시크릿 없음

---

## 인프라 · 시크릿 · git

### [High] 운영 라이브 시크릿이 개발 PC 디스크에 평문 상주 (#8)
- `infra/.env.production.local`에 운영 활성 시크릿 평문 — `OPENAI_API_KEY=sk-proj-...`, `POSTGRES_PASSWORD`, `JWT_SECRET_KEY`, `KAKAO/NAVER_CLIENT_SECRET`, `TOSS_WEBHOOK_SECRET`. **git 미추적은 확인(OK)** 되나 디스크에 무방비.
- **조치:** OpenAI 키·DB 비번 **로테이션(재발급)**, 파일 권한 제한, 장기적으로 암호화 보관(age/1Password).

### [Medium] config fail-fast 부재 / DB비번 하드코딩 / 컨테이너 root (#14,#15)
- `config.py:12` JWT 시크릿 prod 필수 검증 없음, `config.py:33` `POSTGRES_PASSWORD="bideasy_pass"` 하드코딩 기본값 + dev compose가 DB를 `5432:5432`(0.0.0.0) 바인딩.
- `Dockerfile`에 `USER` 미선언(root 구동) + `C_FORCE_ROOT=true`(`compose.prod.yml:58`).
- **조치:** prod에서 필수 시크릿 미설정 시 startup 예외, dev DB는 `127.0.0.1` 바인딩, Dockerfile 비-root USER 추가.

### [Low] 정적 admin 패널 노출 (#21)
- `/admin.html`·`/admin/admin.js`가 인증 게이트 없이 정적 서빙(`default.conf:148`). 실제 권한검사는 API에서 수행하나 UI 구조/엔드포인트 노출.
- **조치:** `/admin` nginx basic-auth 또는 IP allowlist 한 겹.

### ✅ 확인됨 (안전)
- git 히스토리 시크릿 누출 0건, `.env.*.local` 정상 gitignore, 현재 트리 시크릿 스캔 0건
- `.dockerignore`로 `.env`/`.git`/`*.db` 이미지 미포함, 멀티스테이지 빌드
- 운영 compose DB/Redis는 `expose`만(호스트 미바인딩), 이미지 태그 고정
- `deploy.sh` `set -euo pipefail` + `--env-file` + 변수 인용
- CI 시크릿은 더미값만

---

## 권장 조치 순서

1. **즉시(운영 라이브):** 페이플 콜백 재검증 (#1)
2. **이번 주:** SSRF 화이트리스트(#2), 정적 웹 XSS(#3), `.env.production.local` 키 로테이션(#8)
3. **단기:** OAuth state(#4), 소셜 이메일 병합(#5), 토큰 무효화+URL전달(#7), 익스텐션 로그인 브릿지(#6)
4. **정비:** nginx 헤더(#13), config fail-fast(#14), 비인증 엔드포인트(#11), Redis 레이트리밋(#12), 익스텐션 토큰/CSP(#16)
5. **백로그:** 계정열거(#17), 프롬프트 인젝션(#19), 예외 노출(#20), 정적 admin(#21), 회원가입 검증(#22), 기타(#23)

---

*본 보고서는 자동화 감사 + 수동 재검증 결과이며, 각 항목은 실제 코드 라인 근거를 포함한다. 패치 진행 상황은 별도 추적.*
