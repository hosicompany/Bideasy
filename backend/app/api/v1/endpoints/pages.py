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
from app.services.bid_data_quality import base_is_consistent
from app.services.lower_limits import get_lower_limit_rate

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
_KST = timezone(timedelta(hours=9))

# sitemap 프로토콜 상한은 50,000 URL / 50MB. 5,000 으로 잡아 파일당 크기·재생성
# 비용을 낮춘다(공고는 매일 갱신되므로 작은 파일이 크롤 효율에 유리).
SITEMAP_CHUNK = 5000
_SITEMAP_STATIC_PATHS = ["", "/search", "/calculator", "/guide", "/pricing", "/blog"]
_SITEMAP_CACHE_HEADERS = {
    "Cache-Control": "public, max-age=3600, s-maxage=86400, stale-while-revalidate=3600"
}
# SSR 검색 페이지 초기 목록 — 크롤러가 JS 없이 /bid/* 로 갈 경로. 사용자에겐 JS 가
# 즉시 같은 자리를 최신 피드로 덮어쓴다(loadFeed).
SEARCH_SSR_LIMIT = 40


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
    # 마감 90일 후 purge(notice_crawl_tasks) 되므로 색인된 URL 이 사라질 수 있다.
    # 200 + noindex 는 soft-404 로 취급되므로 실제 404 를 준다.
    is_closed = bool(notice and notice.end_date and notice.end_date <= _current_naive_kst())

    # 개찰이 끝났으면 개찰결과가 기초금액·예정가격·낙찰가를 다 갖고 있다.
    # 이걸 안 보면 "알면서 모른다"고 말하는 화면이 된다(실측 4,343건).
    opening = (
        db.query(models.OpeningResult)
        .filter(models.OpeningResult.bid_no == notice.bid_no).first()
        if notice else None
    )

    # 기초금액은 `basis` 단일 소스로만 판단한다. 여기서 basic_price(추정가격)로
    # 폴백하면 틀린 하한선으로 "안전"이라고 말하게 된다 — 그게 이번 사고다.
    from app.services import basis as basis_svc

    _basis_amount, _basis_status = basis_svc.display_basis(notice, opening)
    _basis_unconfirmed = _basis_status == basis_svc.UNCONFIRMED
    _notice_lower = float(getattr(notice, "lower_limit_rate", 0) or 0) if notice else 0
    _a_value = int(getattr(notice, "a_value", 0) or 0) if notice else 0
    _a_source = getattr(notice, "a_value_source", None) if notice else None
    _a_applicable = str(
        getattr(notice, "a_value_applicable", None) or ""
    ).strip().upper() if notice else ""
    if _a_applicable in {"N", "NO", "FALSE", "미적용", "비대상"} and _a_value == 0:
        _a_status = "not_applicable"
    elif _a_value > 0 and _a_source:
        _a_status = "confirmed"
    else:
        _a_status = "unknown"
    _bid_date = notice.start_date.date() if notice and notice.start_date else None
    if _basis_unconfirmed:
        _lower_limit_pct = None
    elif _notice_lower > 0:
        _lower_limit_pct = _notice_lower
    elif ct == "CONSTRUCTION" and _basis_amount:
        _lower_limit_pct = get_lower_limit_rate(
            ct,
            float(_basis_amount),
            _bid_date,
        )
    else:
        _lower_limit_pct = None

    # 개찰 결과 블록 — 사정률은 마감 후에만 알 수 있는 값이라 특히 유용하다
    _result = None
    if opening is not None and (opening.winner_price or 0) > 0:
        _bp = float(opening.basic_price or 0)
        _rp = float(opening.reserved_price or 0)
        _wp = float(opening.winner_price)
        _result = {
            "basic_price": int(_bp) if _bp > 0 else None,
            "reserved_price": int(_rp) if _rp > 0 else None,
            # 사정률 = 예정가격 ÷ 기초금액. 기준이 어긋난 옛 행은 표기하지 않는다.
            "reserved_ratio": (round(_rp / _bp * 100, 3)
                               if base_is_consistent(_bp, _rp) else None),
            "winner_price": int(_wp),
            "winner_rate": round(opening.winner_rate, 3) if opening.winner_rate else None,
            "winner_company": opening.winner_company or None,
            "open_date": (opening.open_date.strftime("%Y-%m-%d %H:%M")
                          if opening.open_date else None),
            "participants": opening.participants_count or None,
        }

    ctx = {
        "request": request,
        "found": bool(notice),
        "basis_unconfirmed": _basis_unconfirmed,
        "bid_no": bid_no,
        "title": (notice.title if (notice and notice.title) else bid_no),
        "organization": getattr(notice, "organization", None) if notice else None,
        "demand_organization": getattr(notice, "demand_organization", None) if notice else None,
        "region": getattr(notice, "region", None) if notice else None,
        "basic_price": _basis_amount,
        "budget_amount": int(getattr(notice, "budget_amount", 0) or 0) if notice else 0,
        "contract_type": ct,
        "contract_type_label": _CT_LABEL.get(ct, "기타"),
        "bid_method": getattr(notice, "bid_method", None) if notice else None,
        "contract_method": getattr(notice, "contract_method", None) if notice else None,
        "opening_date": (getattr(notice, "opening_date", None) if notice else None) or deadline_iso,
        "deadline_iso": deadline_iso,
        "detail_url": getattr(notice, "content", None) if notice else None,
        "a_value": _a_value if _a_status == "confirmed" else 0,
        "a_value_status": _a_status,
        "a_value_source": _a_source,
        "a_value_applicable": _a_applicable or None,
        # 공고 명시값을 우선하고, 시설공사에만 시행일·금액대 표를 쓴다.
        # 용역·물품의 보편 기본값은 만들지 않는다.
        "lower_limit_pct": _lower_limit_pct,
        "prdprc_range_bgn": getattr(notice, "prdprc_range_bgn", None) if notice else None,
        "prdprc_range_end": getattr(notice, "prdprc_range_end", None) if notice else None,
        "bid_date": _bid_date.isoformat() if _bid_date else None,
        "is_closed": is_closed,
        "result": _result,
        "site_url": SITE_URL,
        "api_base": API_BASE,
    }
    return templates.TemplateResponse("bid_detail.html", ctx, status_code=200 if notice else 404)


@router.get("/search", response_class=HTMLResponse)
def search_page(request: Request, db: Session = Depends(get_db)):
    """공고 검색 — SSR 초기 목록 + 기존 클라이언트 검색 UI.

    정적 셸이던 시절엔 라이브 HTML 에 /bid/* 링크가 하나도 없어 크롤러가 공고
    페이지로 갈 내부 경로가 없었다. 서버가 마감 임박 순 초기 목록을 렌더하고,
    JS 는 기존대로 같은 컨테이너를 최신 피드로 교체한다(사용자 경험 무변경).
    """
    now = _current_naive_kst()
    notices = (
        _active_notice_query(db, now)
        .order_by(models.Notice.end_date.asc())
        .limit(SEARCH_SSR_LIMIT)
        .all()
    )
    items = [
        {
            "bid_no": n.bid_no,
            "title": n.title or n.bid_no,
            "organization": n.organization or "",
            "region": n.region or "",
            "contract_type_label": _CT_LABEL.get(n.contract_type or "CONSTRUCTION", "공고"),
            "basic_price": int(n.basic_price or 0),
            "dday": (n.end_date - now).days if n.end_date else None,
        }
        for n in notices
    ]
    return templates.TemplateResponse(
        "search.html", {"request": request, "items": items, "site_url": SITE_URL}
    )


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


def _active_notice_query(db: Session, now: datetime):
    """진행중(마감 전) 공고 쿼리 — sitemap·SSR 목록의 단일 소스."""
    return db.query(models.Notice).filter(
        models.Notice.start_date.isnot(None),
        models.Notice.end_date.isnot(None),
        models.Notice.end_date > now,
    )


def _xml_response(body: str) -> Response:
    return Response(content=body, media_type="application/xml", headers=_SITEMAP_CACHE_HEADERS)


def _urlset(locs: list[str]) -> Response:
    return _xml_response(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "\n".join(locs)
        + "\n</urlset>\n"
    )


def _notice_page_count(db: Session, now: datetime) -> int:
    """공고 sitemap 파일 수 — 공고가 0건이어도 빈 파일 1개는 유지한다."""
    total = _active_notice_query(db, now).count()
    return max(1, -(-total // SITEMAP_CHUNK))  # ceil


@router.get("/sitemap.xml")
def sitemap_index(db: Session = Depends(get_db)):
    """sitemap 인덱스 — 정적·블로그·공고(5,000건 단위 분할) 파일을 가리킨다.

    이전 구현은 단일 urlset 에 진행중 공고 50건만 실었다(문서상 기대치는 5,000건).
    진행중 공고 전량을 색인 대상으로 노출하기 위해 인덱스 구조로 전환한다.
    """
    children = ["/sitemap-static.xml", "/sitemap-blog.xml"]
    children += [
        f"/sitemap-notices-{page}.xml"
        for page in range(1, _notice_page_count(db, _current_naive_kst()) + 1)
    ]
    entries = "\n".join(f"  <sitemap><loc>{SITE_URL}{c}</loc></sitemap>" for c in children)
    return _xml_response(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + entries
        + "\n</sitemapindex>\n"
    )


@router.get("/sitemap-static.xml")
def sitemap_static():
    return _urlset([f"  <url><loc>{SITE_URL}{p}</loc></url>" for p in _SITEMAP_STATIC_PATHS])


@router.get("/sitemap-blog.xml")
def sitemap_blog(db: Session = Depends(get_db)):
    locs = []
    for p in blog_svc.list_posts(db):
        _lm = p.get("updated") or p.get("date") or ""
        _lmtag = f"<lastmod>{xml_escape(str(_lm))}</lastmod>" if _lm else ""
        locs.append(f"  <url><loc>{SITE_URL}/blog/{xml_escape(str(p['slug']))}</loc>{_lmtag}</url>")
    return _urlset(locs)


@router.get("/sitemap-notices-{page}.xml")
def sitemap_notices(page: int, db: Session = Depends(get_db)):
    """진행중 공고 1페이지(최대 SITEMAP_CHUNK 건).

    범위를 벗어난 page 는 빈 urlset 을 준다(404 로 크롤 에러를 만들지 않는다 —
    공고 수는 매일 변하므로 인덱스와 실제 파일 수 사이에 시차가 생길 수 있다).
    """
    now = _current_naive_kst()
    offset = max(0, (page - 1)) * SITEMAP_CHUNK
    notices = (
        _active_notice_query(db, now)
        # start_date is crawler collection time and is biased by category/page order.
        # Fixed-format G2B notice numbers are the best available category-neutral
        # recency proxy, so bid_no DESC is also the deterministic sitemap order.
        .order_by(models.Notice.bid_no.desc())
        .offset(offset)
        .limit(SITEMAP_CHUNK)
        .all()
    )
    # No trustworthy notice modification timestamp exists; collection time is not lastmod.
    return _urlset(
        [f"  <url><loc>{SITE_URL}/bid/{xml_escape(str(n.bid_no))}</loc></url>" for n in notices]
    )
