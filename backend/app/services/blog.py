"""마크다운 파일 기반 블로그 — content/blog/*.md 를 읽어 SSR 렌더.

각 .md 파일 = 프론트매터(--- 구분) + 마크다운 본문.
필수 프론트매터: title, date(YYYY-MM-DD), summary. 선택: slug(없으면 파일명), category, cover, draft.
draft: true 면 목록·sitemap 에서 제외(직접 URL 접근은 noindex 로 미리보기 가능).

새 글은 .md 추가 후 배포(프로세스 재시작)로 반영 — 프로세스 생애 동안 캐시.
"""
from __future__ import annotations
import html as _html
from pathlib import Path
from typing import Optional

from app.core.logging import get_logger

logger = get_logger(__name__)

# backend/content/blog  (이 파일: app/services/blog.py → parents[2] = backend)
BLOG_DIR = Path(__file__).resolve().parents[2] / "content" / "blog"

_CACHE: Optional[list] = None


def _render_markdown(text: str) -> str:
    """마크다운 → HTML. markdown 미설치 시 이스케이프 <pre> 폴백."""
    try:
        import markdown
        return markdown.markdown(text, extensions=["extra", "sane_lists"])
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
    return {
        "slug": meta.get("slug") or path.stem,
        "title": title,
        "date": meta.get("date", ""),
        "category": meta.get("category", ""),
        "summary": meta.get("summary", ""),
        "cover": meta.get("cover", ""),
        "draft": str(meta.get("draft", "")).lower() in ("1", "true", "yes"),
        "body_html": _render_markdown(body.strip()),
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


def list_posts(include_drafts: bool = False) -> list:
    return [p for p in _load_all() if include_drafts or not p["draft"]]


def get_post(slug: str) -> Optional[dict]:
    for p in _load_all():
        if p["slug"] == slug:
            return p
    return None
