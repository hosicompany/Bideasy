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
| **DB `blog_posts`(신규)** | 데이터스토리·자동초안·즉석글 | **런타임(배포 0)** | B / C |

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

## 워크플로 (자동 초안 → 1클릭 발행)
- `status=draft`: 목록·sitemap 제외, 직접 URL 은 noindex 미리보기(파일 draft 와 동일)
- 발행 = `draft→published` + `date` 자동 세팅 (1클릭)
- Track B 자동엔진(③단계)은 `POST /admin/blog` (source=auto, status=draft) 로 초안만 꽂음 → 사람이 `/admin-blog` 에서 검수·발행

## 보존·안전성
- SSR·OG·JSON-LD·**sitemap** 모두 DB 글에 자동 적용(read 경로 단일). `updated`→lastmod. 날짜슬러그(`/blog/weekly-2026-w25`) 지원
- 완전 하위호환: DB 비면 기존과 100% 동일, 파일 4편 무영향, nginx 무변경
- slug 충돌(파일·DB) → 409
- 전체 회귀 **271 passed**

## 배포
`./deploy.sh deploy` 1회 (alembic 마이그레이션 + 앱 재빌드 + 정적 git pull). **이후 DB 글은 재배포 0으로 발행.**

## 다음 (③단계)
주간 Celery → `OpeningResult` 집계 → LLM 초안 → `POST /admin/blog`(draft) → `/admin-blog` 1클릭 발행.
