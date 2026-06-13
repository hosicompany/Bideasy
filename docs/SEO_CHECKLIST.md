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
- 색인된 공고 수 추이 (sitemap에 진행중 공고 최대 5,000건이 자동 노출됨)

색인은 보통 등록 후 1~3주에 걸쳐 천천히 쌓입니다. 조급해하지 마세요.

---

## D. 다음 단계 (2층 — 콘텐츠)

블로그 4편을 깔았으니, 이걸 네이버 블로그/카페로 확산하는 게 2층입니다. 준비되면 말씀 주세요.
