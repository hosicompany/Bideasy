"""마크다운 파일 기반 블로그 — content/blog/*.md 를 읽어 SSR 렌더.

각 .md 파일 = 프론트매터(--- 구분) + 마크다운 본문.
필수 프론트매터: title, date(YYYY-MM-DD), summary. 선택: slug(없으면 파일명), category, cover, draft.
draft: true 면 목록·sitemap 에서 제외(직접 URL 접근은 noindex 로 미리보기 가능).

새 글은 .md 추가 후 배포(프로세스 재시작)로 반영 — 프로세스 생애 동안 캐시.
"""
from __future__ import annotations
import html as _html
import re
from pathlib import Path
from typing import Optional

from app.core.logging import get_logger

logger = get_logger(__name__)

# backend/content/blog  (이 파일: app/services/blog.py → parents[2] = backend)
BLOG_DIR = Path(__file__).resolve().parents[2] / "content" / "blog"

_CACHE: Optional[list] = None

# 블로그 글쓴이 — 브랜드 단일(가짜 인물 없음).
BLOG_AUTHOR = {
    "name": "BidEasy",
    "avatar": "/brand/bideasy-mark.svg",
    "bio": "공공입찰 데이터로 적자 수주를 막는 입찰 안전 비서.",
}

# 단독 이미지 단락(<p><img></p>) → <figure> 변환용
_IMG_P_RE = re.compile(r"<p>(<img\b[^>]*>)</p>")


def _figureize(html_str: str) -> str:
    """단독 이미지 <p><img></p> → <figure> + 캡션(alt). lazy-load 속성 주입."""
    def repl(m: "re.Match") -> str:
        img = m.group(1)
        if "loading=" not in img:
            img = re.sub(r"\s*/?>\s*$", ' loading="lazy" decoding="async">', img)
        alt = re.search(r'alt="([^"]*)"', img)
        cap = f"<figcaption>{alt.group(1)}</figcaption>" if (alt and alt.group(1).strip()) else ""
        return f"<figure>{img}{cap}</figure>"
    return _IMG_P_RE.sub(repl, html_str)


def _reading_time(raw: str) -> int:
    """한국어 = 글자 수 기반(분당 ~500자). 마크다운 변환 전 raw 에서 계산."""
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", raw)   # 이미지 마크다운 제거
    text = re.sub(r"[#>*`\-\|\[\]()]", "", text)       # 마크다운 기호 제거
    chars = len(re.sub(r"\s+", "", text))
    return max(1, round(chars / 500))


def _render_markdown(text: str) -> str:
    """마크다운 → HTML. markdown 미설치 시 이스케이프 <pre> 폴백."""
    try:
        import markdown
        html_str = markdown.markdown(text, extensions=["extra", "sane_lists", "attr_list"])
        return _figureize(html_str)
    except Exception as e:  # pragma: no cover - 폴백 경로
        logger.warning(f"markdown render fallback ({e})")
        return "<pre>" + _html.escape(text) + "</pre>"


def _parse_file(path: Path) -> Optional[dict]:
    raw = path.read_text(encoding="utf-8")
    meta: dict = {}
    body = raw
    lines = raw.splitlines()
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                for fl in lines[1:i]:
                    if ":" in fl:
                        k, v = fl.split(":", 1)
                        meta[k.strip()] = v.strip()
                body = "\n".join(lines[i + 1:])
                break
    title = meta.get("title")
    if not title:
        return None  # 제목 없는 파일은 건너뜀
    body = body.strip()
    cover = meta.get("cover", "")
    date = meta.get("date", "")
    return {
        "slug": meta.get("slug") or path.stem,
        "title": title,
        "date": date,
        "updated": meta.get("updated", "") or date,
        "category": meta.get("category", ""),
        "summary": meta.get("summary", ""),
        "cover": cover,
        "hero": meta.get("hero", "") or cover,
        "tags": [t.strip() for t in meta.get("tags", "").split(",") if t.strip()],
        "draft": str(meta.get("draft", "")).lower() in ("1", "true", "yes"),
        "reading_time": _reading_time(body),
        "author": BLOG_AUTHOR["name"],
        "author_avatar": BLOG_AUTHOR["avatar"],
        "author_bio": BLOG_AUTHOR["bio"],
        "body_html": _render_markdown(body),
    }


def _scan() -> list:
    posts = []
    if not BLOG_DIR.exists():
        return posts
    for p in sorted(BLOG_DIR.glob("*.md")):
        try:
            post = _parse_file(p)
            if post:
                posts.append(post)
        except Exception as e:
            logger.warning(f"blog parse failed {p.name}: {e}")
    posts.sort(key=lambda x: x["date"], reverse=True)
    return posts


def _load_all(force: bool = False) -> list:
    global _CACHE
    if _CACHE is None or force:
        _CACHE = _scan()
    return _CACHE


def render(body_md: str) -> tuple:
    """마크다운 본문 → (렌더 HTML, 읽는 시간). DB 글 저장 시 재사용 (파일과 동일 파이프라인)."""
    return _render_markdown(body_md), _reading_time(body_md)


def _db_to_dict(post) -> dict:
    """BlogPost(ORM) → 마크다운 post 와 동형 dict. author 는 BLOG_AUTHOR 주입."""
    date = post.date or ""
    updated = ""
    if post.updated_at:
        try:
            updated = post.updated_at.date().isoformat()
        except Exception:
            updated = ""
    cover = post.cover or ""
    return {
        "slug": post.slug,
        "title": post.title,
        "date": date,
        "updated": updated or date,
        "category": post.category or "",
        "summary": post.summary or "",
        "cover": cover,
        "hero": post.hero or cover,
        "tags": [t.strip() for t in (post.tags or "").split(",") if t.strip()],
        "draft": post.status != "published",
        "reading_time": post.reading_time or 1,
        "author": BLOG_AUTHOR["name"],
        "author_avatar": BLOG_AUTHOR["avatar"],
        "author_bio": BLOG_AUTHOR["bio"],
        "body_html": post.body_html or "",
    }


def _db_posts(db, include_drafts: bool = False) -> list:
    """DB 글 → dict 목록. db 없으면 빈 목록(하위호환)."""
    if db is None:
        return []
    from app.db import models  # 지연 임포트 (순환 방지)
    q = db.query(models.BlogPost)
    if not include_drafts:
        q = q.filter(models.BlogPost.status == "published")
    return [_db_to_dict(p) for p in q.all()]


def list_posts(db=None, include_drafts: bool = False) -> list:
    """마크다운 파일 + DB 글 병합. slug 중복 시 파일 우선. date 내림차순."""
    md = [p for p in _load_all() if include_drafts or not p["draft"]]
    seen = {p["slug"] for p in md}
    merged = md + [p for p in _db_posts(db, include_drafts) if p["slug"] not in seen]
    merged.sort(key=lambda x: x.get("date") or "", reverse=True)
    return merged


def get_post(slug: str, db=None) -> Optional[dict]:
    """파일 먼저 → 없으면 DB. 직접 URL 은 draft 도 반환(noindex 미리보기)."""
    for p in _load_all():
        if p["slug"] == slug:
            return p
    if db is not None:
        from app.db import models  # 지연 임포트
        row = db.query(models.BlogPost).filter(models.BlogPost.slug == slug).first()
        if row:
            return _db_to_dict(row)
    return None
