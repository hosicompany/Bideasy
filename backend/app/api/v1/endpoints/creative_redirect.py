"""승인 Creative의 내부 랜딩만 허용하는 추적 리디렉션."""

from __future__ import annotations

import re
import secrets
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import models
from app.db.session import get_db


router = APIRouter()
_ALLOWED_LANDING_EXACT = {
    "/", "/calculator", "/calculator.html", "/diagnose", "/diagnose.html",
    "/signup", "/signup.html", "/guide", "/guide.html", "/pricing", "/pricing.html",
}
_ALLOWED_LANDING_PREFIXES = ("/blog/", "/bid/")


def safe_landing_path(value: str) -> str:
    path = (value or "").strip()
    parsed = urlsplit(path)
    decoded_path = unquote(parsed.path)
    if (
        not path.startswith("/")
        or path.startswith("//")
        or parsed.scheme
        or parsed.netloc
        or parsed.fragment
        or "\\" in path
        or "\\" in decoded_path
        or any(ord(char) < 32 for char in path)
        or any(ord(char) < 32 for char in decoded_path)
        or any(part == ".." for part in decoded_path.split("/"))
    ):
        raise HTTPException(status_code=400, detail="허용되지 않은 랜딩 경로입니다.")
    base = parsed.path
    if base not in _ALLOWED_LANDING_EXACT and not any(base.startswith(prefix) for prefix in _ALLOWED_LANDING_PREFIXES):
        raise HTTPException(status_code=400, detail="허용되지 않은 랜딩 경로입니다.")
    return path


@router.get("/go/{creative_id}")
def creative_redirect(
    creative_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    creative = (
        db.query(models.CreativeBrief)
        .filter(models.CreativeBrief.id == creative_id)
        .first()
    )
    if creative is None or creative.status not in ("APPROVED", "PUBLISHED"):
        raise HTTPException(status_code=404, detail="게시 승인된 크리에이티브가 아닙니다.")

    landing = safe_landing_path(creative.landing_path)
    parsed_landing = urlsplit(landing)
    base = parsed_landing.path
    reserved = {
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_content",
        "creative_id",
    }
    existing = [
        (key, value)
        for key, value in parse_qsl(parsed_landing.query, keep_blank_values=True)
        if key not in reserved
    ]
    params = {
        "utm_source": creative.utm_source,
        "utm_medium": creative.utm_medium,
        "utm_campaign": creative.utm_campaign,
        "utm_content": creative.variant or creative.concept_key,
        "creative_id": str(creative.id),
    }
    canonical = [(key, value) for key, value in params.items() if value]
    query = urlencode(existing + canonical)
    target = f"{base}?{query}" if query else base

    # bd_go_anon은 서버 추적용(HttpOnly), bd_anon은 정적 페이지의 성장 이벤트가
    # 같은 익명 여정을 이어받기 위한 최소 식별자다. 기존 서버 쿠키를 우선해
    # 브라우저 스크립트가 임의로 바꾼 값으로 first-touch가 갈라지지 않게 한다.
    anonymous_id = (
        request.cookies.get("bd_go_anon")
        or request.cookies.get("bd_anon")
        or ""
    )
    if not re.fullmatch(r"[A-Za-z0-9_-]{20,80}", anonymous_id):
        anonymous_id = secrets.token_urlsafe(24)

    db.add(models.GrowthEvent(
        event_name="qualified_visit",
        dedupe_key=f"creative-go:{creative.id}:{anonymous_id}",
        anonymous_id=anonymous_id,
        creative_id=creative.id,
        utm_source=creative.utm_source,
        utm_medium=creative.utm_medium,
        utm_campaign=creative.utm_campaign,
        utm_content=creative.variant or creative.concept_key,
        event_metadata_json={
            "referrer": (request.headers.get("referer") or "")[:300],
            "user_agent": (request.headers.get("user-agent") or "")[:300],
        },
    ))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
    response = RedirectResponse(url=target, status_code=302)
    response.set_cookie(
        "bd_go_anon",
        anonymous_id,
        max_age=60 * 60 * 24 * 90,
        secure=True,
        httponly=True,
        samesite="lax",
    )
    response.set_cookie(
        "bd_anon",
        anonymous_id,
        max_age=60 * 60 * 24 * 90,
        secure=True,
        httponly=False,
        samesite="lax",
    )
    return response
