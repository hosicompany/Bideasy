"""블로그 초안 로컬 점검 — 검수 게이트 결정적 검사 + 실제 블로그 템플릿 미리보기.

사용: backend/.venv/bin/python backend/scripts/blog_draft_check.py <draft.md> [<out_dir>]
draft.md 는 front-matter(title/slug/summary/category/tags) + 본문 마크다운.
결과: <out_dir>/checks.json, <out_dir>/preview.html (out_dir 기본 = draft.md 폴더).
LLM 심판은 돌리지 않는다(서버 OpenRouter 비용 0) — 사람이 미리보기로 검토한다.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from jinja2 import Environment, FileSystemLoader  # noqa: E402

from app.services import blog, content_review as cr  # noqa: E402


def main(md_path: str, out_dir: str = "") -> int:
    src = Path(md_path)
    _, fm, body = src.read_text(encoding="utf-8").split("---\n", 2)
    meta = dict(line.split(": ", 1) for line in fm.strip().splitlines())
    text = f"{meta['title']}\n{meta['summary']}\n{body}"
    checks = [cr.check_banned_terms(text), cr.check_unsourced_numbers(text),
              cr.check_structure(body), cr.check_image_refs(body, meta["slug"])]
    html, minutes = blog.render(body)
    post = dict(title=meta["title"], summary=meta["summary"], slug=meta["slug"],
                category=meta.get("category", ""), tags=[t.strip() for t in meta.get("tags", "").split(",") if t.strip()],
                body_html=html, reading_time=minutes, date="", author="BidEasy 에디터",
                author_avatar="/brand/favicon.svg", draft=True, hero=None, blocks=None, updated=None)
    page = Environment(loader=FileSystemLoader(str(ROOT / "templates"))).get_template("blog_detail.html").render(
        found=True, post=post, site_url="https://bideasy.kr")
    out = Path(out_dir) if out_dir else src.parent
    out.mkdir(parents=True, exist_ok=True)
    (out / "preview.html").write_text(page.replace("<head>", '<head><base href="https://bideasy.kr/">', 1), encoding="utf-8")
    result = {"slug": meta["slug"], "chars": len(body), "reading_time": minutes,
              "checks": [{"code": c["code"], "level": c["level"], "detail": c.get("detail"), "hits": c.get("hits", [])[:10]} for c in checks]}
    (out / "checks.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    for c in result["checks"]:
        print(c["code"], c["level"], c["detail"])
    return 1 if any(c["level"] == "FAIL" for c in result["checks"]) else 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:3]))
