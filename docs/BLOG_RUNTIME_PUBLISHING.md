# 블로그 런타임 발행 구조 (하이브리드) — 설계·구현

> 목적: 새 글(특히 Track B 자동 데이터스토리)을 **배포 없이** `/blog` 에 발행. 손으로 쓰는 상록수 가이드는 git 마크다운 그대로 유지. 자동 발행(③단계)의 전제 인프라.

## 진단 (왜 기존엔 막혔나)
- `content/blog/*.md` 가 **앱 이미지에 구워짐** → 새 글 = 이미지 재빌드 필요
- `services/blog.py` 의 `_CACHE` 모듈 전역이 **프로세스 1회 로드** 후 고정 → 재시작 전 미반영
- 결국 발행 = 커밋+배포+재시작

## 결정: 하이브리드 (트랙과 1:1)
| 소스 | 담는 것 | 발행 | 캘린더 트랙 |
|---|---|---|---|
| 마크다운 파일(유지) | 상록수 가이드(손으로) | git 커밋→배포 | A |
| **DB `blog_posts`(신규)** | 데이터스토리·입찰상식 자동초안·즉석글 | **런타임(배포 0)** | B / K / C |

읽는 경로(`list_posts`/`get_post`)만 하나로 병합. slug 중복 시 **파일 우선**.

## 구현 파일
- `app/db/models.py` — `BlogPost` (slug uniq · title · summary · category · tags · cover · hero · body_md · body_html · reading_time · status[draft|published] · source[admin|auto] · date · publish_at · created/updated_at)
- `alembic/versions/e1a4c7b2f039_add_blog_posts_table.py` — 테이블 생성 (down_revision=d5a2b8c14e90)
- `app/services/blog.py` — `list_posts(db, include_drafts)` / `get_post(slug, db)` 가 파일+DB 병합, `_db_to_dict()` 가 마크다운과 동형 dict 로 매핑(author=BLOG_AUTHOR 주입), `render()` 가 저장 시 동일 렌더 파이프라인 재사용
- `app/schemas/blog.py` — Create/Update/Out
- `app/api/v1/endpoints/admin/blog.py` — `GET/POST /admin/blog`, `GET/PUT/DELETE /admin/blog/{id}`, `POST /admin/blog/{id}/publish|unpublish` (전부 require_admin)
- `app/api/v1/endpoints/pages.py` — `/blog`·`/blog/{slug}`·sitemap 에 `db` 주입
- `infra/nginx/html/admin-blog.html` — 관리자 에디터(목록·작성·발행·미리보기·삭제), `/admin-blog`
- `infra/nginx/html/admin.html` — 사이드바에 "✍️ 블로그" 링크
- `tests/test_blog_admin.py` — 9 케이스

## 워크플로 (자동 초안 → 검수 판정 라우팅)
- `status=draft`: 목록·sitemap 제외, 직접 URL 은 noindex 미리보기(파일 draft 와 동일)
- 발행 = `draft→published` + `date` 자동 세팅 (1클릭)
- Track B 데이터스토리: 최소 데이터 임계 통과 → 유예 예약 → 매시 자동발행
- Track K 입찰상식: 수요일 07:00 초안·자동 검수 → 완결된 PASS/WARN만 48시간 유예 예약 → 금요일 07:05 이후 자동발행. FAIL·검사 미완료는 draft 유지 + 관리자 알림
- 사람이 자동 생성 글의 제목·본문을 수정하거나 force 재생성하면 기존 검수 판정·파생 자산·예약이 무효화된다. 명시적 1클릭 publish는 사람 override로 유지한다.

## 보존·안전성
- SSR·OG·JSON-LD·**sitemap** 모두 DB 글에 자동 적용(read 경로 단일). `updated`→lastmod. 날짜슬러그(`/blog/weekly-2026-w25`) 지원
- 완전 하위호환: DB 비면 기존과 100% 동일, 파일 4편 무영향, nginx 무변경
- slug 충돌(파일·DB) → 409
- K-트랙 발행 직전 검수 재확인 + 히어로 HTTP 확인. 불완전 검수는 예약 해제, 미확인 히어로는 비운 뒤 텍스트만 발행
- 운영 Postgres에서는 due 행을 `FOR UPDATE SKIP LOCKED`로 선점해 Celery 재전달·중복 실행의 이중 발행 알림과 채널 파생을 막는다.

## 배포
`./deploy.sh deploy` 1회 (alembic 마이그레이션 + 앱 재빌드 + 정적 git pull). **이후 DB 글은 재배포 0으로 발행.**

## 현재 자동화 경계
블로그 B/K 트랙은 런타임 자동발행까지 연결됐다. 파일 상록수와 네이버·인스타·유튜브 등 외부 채널 게시에는 사람 최종 확인을 유지한다.
