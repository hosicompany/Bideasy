"""공개 SEO 페이지 (SSR) — 공고 상세 + sitemap + robots.

`/api/v1` 밖 root 경로에 마운트 (main.py). nginx 가 `/bid/`·`/sitemap.xml`·
`/robots.txt` 를 bideasy_api 로 proxy. 공고 1건=고유 URL = 롱테일 SEO 엔진.
서버에서 title/OG/JSON-LD 를 렌더해 크롤러가 JS 없이 본문 인식.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db import models
from app.core.logging import get_logger
from app.core.config import settings
from app.api.v1.endpoints.bids import _lookup_notice, get_bid_context
from app.services import blog as blog_svc

logger = get_logger(__name__)
router = APIRouter()

# backend/templates  (이 파일: app/api/v1/endpoints/pages.py → parents[4]=backend)
_TEMPLATES_DIR = Path(__file__).resolve().parents[4] / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
# SSR 템플릿 공통 전역 — 검색엔진 소유확인 메타(빈 값이면 미출력)
templates.env.globals["google_verification"] = settings.GOOGLE_SITE_VERIFICATION
templates.env.globals["naver_verification"] = settings.NAVER_SITE_VERIFICATION

SITE_URL = "https://bideasy.kr"
API_BASE = "https://api.bideasy.kr/api/v1"

_CT_LABEL = {"CONSTRUCTION": "공사", "SERVICE": "용역", "GOODS": "물품"}
_LOWER_LIMIT = {"CONSTRUCTION": 87.745, "SERVICE": 60.0, "GOODS": 0.0}
_KST = timezone(timedelta(hours=9))


def _current_naive_kst(instant: datetime | None = None) -> datetime:
    """Return an instant as naive KST, matching naive G2B API datetimes in the DB."""
    aware_instant = instant or datetime.now(timezone.utc)
    if aware_instant.tzinfo is None or aware_instant.utcoffset() is None:
        raise ValueError("instant must be timezone-aware")
    return aware_instant.astimezone(_KST).replace(tzinfo=None)


def _resolve_notice(db: Session, bid_no: str):
    """DB 캐시 → 없으면 context 엔드포인트로 fetch+적재 후 재조회."""
    notice = _lookup_notice(db, bid_no)
    if notice:
        return notice
    try:
        get_bid_context(bid_no, db)  # side-effect: OpenAPI fetch + DB save
    except Exception as e:
        logger.warning(f"bid_detail_page fetch failed for {bid_no}: {e}")
    return _lookup_notice(db, bid_no)


@router.get("/bid/{bid_no}", response_class=HTMLResponse)
def bid_detail_page(bid_no: str, request: Request, db: Session = Depends(get_db)):
    notice = _resolve_notice(db, bid_no)
    ct = (getattr(notice, "contract_type", None) or "CONSTRUCTION") if notice else "CONSTRUCTION"
    deadline_iso = notice.end_date.isoformat() if (notice and notice.end_date) else None

    ctx = {
        "request": request,
        "found": bool(notice),
        "bid_no": bid_no,
        "title": (notice.title if (notice and notice.title) else bid_no),
        "organization": getattr(notice, "organization", None) if notice else None,
        "demand_organization": getattr(notice, "demand_organization", None) if notice else None,
        "region": getattr(notice, "region", None) if notice else None,
        "basic_price": int(notice.basic_price or 0) if notice else 0,
        "budget_amount": int(getattr(notice, "budget_amount", 0) or 0) if notice else 0,
        "contract_type": ct,
        "contract_type_label": _CT_LABEL.get(ct, "기타"),
        "bid_method": getattr(notice, "bid_method", None) if notice else None,
        "contract_method": getattr(notice, "contract_method", None) if notice else None,
        "opening_date": (getattr(notice, "opening_date", None) if notice else None) or deadline_iso,
        "deadline_iso": deadline_iso,
        "detail_url": getattr(notice, "content", None) if notice else None,
        "a_value": int(getattr(notice, "a_value", 0) or 0) if notice else 0,
        "lower_limit_pct": _LOWER_LIMIT.get(ct, 0.0),
        "site_url": SITE_URL,
        "api_base": API_BASE,
    }
    return templates.TemplateResponse("bid_detail.html", ctx)


@router.get("/blog", response_class=HTMLResponse)
def blog_list_page(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(
        "blog_list.html",
        {"request": request, "posts": blog_svc.list_posts(db), "site_url": SITE_URL},
    )


@router.get("/blog/{slug}", response_class=HTMLResponse)
def blog_detail_page(slug: str, request: Request, db: Session = Depends(get_db)):
    post = blog_svc.get_post(slug, db)
    return templates.TemplateResponse(
        "blog_detail.html",
        {"request": request, "post": post, "found": bool(post), "slug": slug, "site_url": SITE_URL},
        status_code=200 if post else 404,
    )


@router.get("/robots.txt", response_class=PlainTextResponse)
def robots():
    return f"User-agent: *\nAllow: /\nSitemap: {SITE_URL}/sitemap.xml\n"


@router.get("/sitemap.xml")
def sitemap(db: Session = Depends(get_db)):
    """정적·발행 블로그와 최신 진행중 공고 최대 50건을 나열한다."""
    now = _current_naive_kst()
    notices = (
        db.query(models.Notice)
        .filter(
            models.Notice.start_date.isnot(None),
            models.Notice.end_date.isnot(None),
            models.Notice.end_date > now,
        )
        # start_date is crawler collection time and is biased by category/page order.
        # Fixed-format G2B notice numbers are the best available category-neutral
        # recency proxy, so bid_no DESC is also the deterministic sitemap order.
        .order_by(models.Notice.bid_no.desc())
        .limit(50)
        .all()
    )
    static_paths = ["", "/search", "/calculator", "/guide", "/pricing", "/blog"]
    locs = [f"  <url><loc>{SITE_URL}{p}</loc></url>" for p in static_paths]
    for p in blog_svc.list_posts(db):
        _lm = p.get("updated") or p.get("date") or ""
        _lmtag = f"<lastmod>{xml_escape(str(_lm))}</lastmod>" if _lm else ""
        locs.append(f"  <url><loc>{SITE_URL}/blog/{xml_escape(str(p['slug']))}</loc>{_lmtag}</url>")
    for n in notices:
        # No trustworthy notice modification timestamp exists; collection time is not lastmod.
        locs.append(f"  <url><loc>{SITE_URL}/bid/{xml_escape(str(n.bid_no))}</loc></url>")
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "\n".join(locs)
        + "\n</urlset>\n"
    )
    return Response(
        content=xml,
        media_type="application/xml",
        headers={
            "Cache-Control": "public, max-age=3600, s-maxage=86400, stale-while-revalidate=3600"
        },
    )
