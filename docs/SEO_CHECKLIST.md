# BidEasy SEO 1층 — 배포 & 사용자 액션 체크리스트

> 작성: 2026-06-13 / 마케팅 1층(SEO) 작업 직후

## A. 코드 변경 (완료 — 배포만 하면 됨)

이번 작업으로 반영된 것:

- **sitemap에 정적 페이지 추가** — 홈·검색·계산기·가이드·요금제·블로그 (`pages.py`)
- **www → bideasy.kr 301 리다이렉트** — 중복 색인 방지 (`nginx default.conf`)
- **정적 페이지 canonical + OpenGraph 태그** — index/search/calculator/guide/pricing
- **계산기 페이지 키워드 강화** — title에 "낙찰하한율 계산기" + FAQ 구조화데이터(JSON-LD)
- **홈 SoftwareApplication 구조화데이터**
- **블로그 글 3편 신규** — 낙찰하한율 / 투찰가 계산법 / 독소조항 5가지 (기존 A값 글 + 총 4편)

### 배포 명령
```bash
cd ~/Bideasy/infra && ./deploy.sh deploy
```
nginx 설정 변경이 포함됐으니 배포 후 `./deploy.sh status`로 nginx 컨테이너 정상 기동 확인.
배포 후 확인: `https://www.bideasy.kr/calculator` 접속 시 `https://bideasy.kr/calculator`로 튕기는지.

---

## B. 사용자 액션 (코드로 못 함 — 직접 해야 함)

우선순위 순. 한 번만 하면 됩니다. 총 30~40분.

### 1. 네이버 서치어드바이저 등록 ★ 최우선
타겟이 네이버를 가장 많이 씁니다. 여기가 1순위.

1. https://searchadvisor.naver.com → 로그인 → **웹마스터 도구**
2. 사이트 등록: `https://bideasy.kr`
3. 소유확인 — **HTML 태그** 방식 선택 → `<meta name="naver-site-verification" content="xxxx">` 복사
4. 그 메타태그를 알려주시면 제가 `index.html` `<head>`에 넣고 재배포해 드립니다. (또는 직접 넣어도 됨)
5. 확인 완료 후 → **요청 > 사이트맵 제출**: `https://bideasy.kr/sitemap.xml`
6. **요청 > 웹페이지 수집**에 주요 URL 직접 제출(색인 가속): 홈, /calculator, /search, /blog

### 2. 구글 서치콘솔 등록
1. https://search.google.com/search-console → `URL 접두어`로 `https://bideasy.kr` 추가
2. 소유확인 — HTML 태그 방식 → 메타태그 받아서 1번과 동일하게 처리
3. **Sitemaps** 메뉴 → `sitemap.xml` 제출
4. **URL 검사**로 홈·계산기 색인 요청

### 3. 다음(카카오) 검색 등록 (선택)
https://register.search.daum.net/index.daum → 사이트 등록만 해두기. 5분.

---

## C. 등록 후 2주 체크포인트

- 네이버 서치어드바이저 **수집 현황** — `/bid/*` 공고 페이지가 색인되기 시작하는지
- 구글 서치콘솔 **실적** — 노출(impressions) 키워드 확인. "낙찰하한율", "투찰가 계산" 같은 단어가 뜨기 시작하면 1층이 작동하는 것
- 색인된 공고 수 추이

> **2026-07-27 정정**: 이 문서는 오랫동안 "sitemap에 진행중 공고 최대 5,000건이 자동 노출됨"이라고 적혀 있었으나, **코드는 50건 상한이었다**(`pages.py` `.limit(50)`). 같은 날 sitemap 인덱스 구조로 전환해 **진행중 공고 전량**을 5,000건 단위로 분할 노출하도록 수정했다. 제출 대상은 여전히 `https://bideasy.kr/sitemap.xml`(이제 인덱스) 하나이며, 하위 파일은 `/sitemap-static.xml`·`/sitemap-blog.xml`·`/sitemap-notices-{N}.xml`. 함께 `/search`를 SSR로 바꿔 크롤러가 `/bid/*`로 들어갈 내부 링크 경로를 열었고, 없는 공고는 soft-404(200+noindex) 대신 실제 404를 반환한다. → 배경·후속은 `GROWTH_STRATEGY.md`.

색인은 보통 등록 후 1~3주에 걸쳐 천천히 쌓입니다. 조급해하지 마세요.

---

## C-2. 색인 통보 (IndexNow) — 2026-07-27 추가

**구글 sitemap ping 은 죽었다.** `https://www.google.com/ping?sitemap=` 은 2023-06 폐지 예고 후 현재 404 (인증 없는 제출의 대부분이 스팸이라는 이유). 구글의 공식 경로는 **robots.txt 선언 + 서치콘솔** 둘뿐이며, 우리는 robots.txt 에 이미 선언돼 있어 **재제출은 가속용이지 필수가 아니다**(sitemap URL 이 안 바뀌었으므로 구글이 알아서 다시 읽는다).

**네이버는 IndexNow 로 자동화했다.** 네이버는 2023-07 부터 IndexNow 를 지원하며 **서치어드바이저 로그인 없이** 키만 공개하면 URL 통보가 가능하다.

| 항목 | 값 |
|---|---|
| 키 | `INDEXNOW_KEY` (config.py) — **비밀 아님**, 공개가 프로토콜 요구사항 |
| 키 파일 | `https://bideasy.kr/{KEY}.txt` (`infra/nginx/html/{KEY}.txt`) |
| 발송 대상 | 네이버 직접 + `api.indexnow.org`(Bing 등 참여 엔진 공유) |
| 자동 발송 시점 | 블로그 발행(수동·예약) · 일일 공고 수집 후 신규 URL |
| 일괄 통보(일회성) | `scripts/indexnow_backfill.py` — 배포 에이전트 `indexnow-backfill` 액션 |
| 안전장치 | `APP_ENV=production` + 키 설정 시에만 발송, 회당 상한 `MAX_PER_RUN`, 실패는 비치명적(호출부 안 되돌림) |

⚠️ **IndexNow 는 통보이지 색인 보장이 아니다.** 반영 여부·시점은 검색엔진이 정한다. 효과 판정은 서치어드바이저 **수집 현황**으로 2주 뒤 확인한다.

---

## D. 다음 단계 (2층 — 콘텐츠)

블로그 4편을 깔았으니, 이걸 네이버 블로그/카페로 확산하는 게 2층입니다. 준비되면 말씀 주세요.
