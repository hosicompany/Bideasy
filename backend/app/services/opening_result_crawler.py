"""
개찰결과 일일 크롤러
====================
data.go.kr 조달청_나라장터 공공데이터개방표준서비스 API 로 최근 개찰된
공사 입찰의 낙찰 결과를 가져와 opening_results 테이블에 저장.

API 특성:
- 단건 조회(`inqryDiv=4 + bidNtceNo`) 는 "필수값 입력 에러" 반환 (param 호환성 미지)
- 일자 범위 조회 (`opengBgnDt/opengEndDt` + `bsnsDivCd=3`) 만 정상 작동
- 따라서 매일 어제 분량을 일괄 크롤 → DB upsert 방식 사용

호출처:
- Celery task: app/tasks/verification_tasks.py:daily_crawl_opening_results
- 수동: docker compose exec app python -c "from app.services.opening_result_crawler import crawl_recent_openings; crawl_recent_openings(days_back=2)"
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import requests
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db import models
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)

_BASE_URL = "https://apis.data.go.kr/1230000/ao/PubDataOpnStdService/getDataSetOpnStdScsbidInfo"
_BSNS_DIV_CONSTRUCTION = "3"  # 공사


def _fetch_page(start_dt: str, end_dt: str, page: int = 1, num_rows: int = 100) -> list[dict]:
    """1 페이지 조회. params 는 crawl_opening_results.py 의 검증된 조합 사용."""
    params = {
        "serviceKey": settings.PUBLIC_DATA_KEY,
        "numOfRows": num_rows,
        "pageNo": page,
        "type": "json",
        "bsnsDivCd": _BSNS_DIV_CONSTRUCTION,
        "opengBgnDt": start_dt,
        "opengEndDt": end_dt,
    }
    try:
        resp = requests.get(_BASE_URL, params=params, timeout=60, verify=False)
        if resp.status_code != 200:
            logger.warning(f"opening_crawler: HTTP {resp.status_code}")
            return []
        data = resp.json()
        err = data.get("nkoneps.com.response.ResponseError", {})
        if err:
            logger.warning(f"opening_crawler: API error {err.get('header', {}).get('resultMsg', '')}")
            return []
        items = data.get("response", {}).get("body", {}).get("items", []) or []
        return [items] if isinstance(items, dict) else items
    except Exception as e:  # noqa: BLE001
        logger.warning(f"opening_crawler: {type(e).__name__}: {e}")
        return []


def _parse_item_to_kwargs(item: dict) -> dict | None:
    """API 응답 item 을 OpeningResult 모델 kwargs 로 변환.

    None 반환 = skip (필수 필드 누락).
    """
    bid_no_raw = item.get("bidNtceNo")
    ord_raw = item.get("bidNtceOrd")
    if not bid_no_raw:
        return None
    bid_no = f"{bid_no_raw}-{ord_raw or '000'}"

    # 가격 파싱 (str -> float)
    def _f(v):
        if v in (None, ""):
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    basic_price = _f(item.get("presmptPrce"))  # 기초금액
    reserved_price = _f(item.get("plnprc"))  # 예정가격
    winner_price = _f(item.get("scsbidPrce"))  # 낙찰금액
    winner_rate = _f(item.get("scsbidRate"))   # 낙찰률

    if not winner_price or winner_price <= 0:
        return None

    # 낙찰률이 없거나 0 이면 계산
    if (not winner_rate or winner_rate <= 0) and basic_price and basic_price > 0:
        winner_rate = round(winner_price / basic_price * 100, 4)

    # opengDt: "2026-05-19 11:00:00" or "20260519110000" 형태 가능
    open_dt = item.get("opengDt") or item.get("scsbidDecsnDt")
    parsed_open_dt = None
    if open_dt:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y%m%d%H%M%S", "%Y-%m-%d"):
            try:
                parsed_open_dt = datetime.strptime(str(open_dt)[:19].replace("-", "-"), fmt)
                break
            except (ValueError, TypeError):
                continue

    return {
        "bid_no": bid_no,
        "organization": item.get("ntceInsttNm") or item.get("dminsttNm") or "",
        "region": item.get("prtcptLmtRgnNm") or "",
        "open_date": parsed_open_dt,
        "basic_price": basic_price,
        "reserved_price": reserved_price,
        "bid_method": item.get("bidMthdNm") or "",
        "winner_company": item.get("scsbidCorpNm") or "",
        "winner_price": winner_price,
        "winner_rate": winner_rate,
        "participants_count": None,  # 본 API 응답에 없음, 다른 API 필요
        "crawled_at": datetime.now(timezone.utc),
    }


def _upsert_opening_result(db: Session, kwargs: dict) -> bool:
    """OpeningResult upsert. 반환: 신규 삽입 True / 업데이트 False."""
    bid_no = kwargs["bid_no"]
    existing = db.query(models.OpeningResult).filter(
        models.OpeningResult.bid_no == bid_no
    ).first()
    if existing:
        # winner_price 가 채워져있으면 갱신 안 함 (실 결과는 변경 X)
        if existing.winner_price:
            return False
        for k, v in kwargs.items():
            if v is not None:
                setattr(existing, k, v)
        return False
    db.add(models.OpeningResult(**kwargs))
    return True


def crawl_recent_openings(days_back: int = 2, max_pages: int = 20) -> dict:
    """최근 N일 (기본 2일) 동안 개찰된 공사 결과 일괄 크롤 → DB upsert.

    매일 Celery beat 가 호출. days_back=2 로 안전마진(하루 누락 방지).
    """
    end_dt = datetime.now()
    start_dt = end_dt - timedelta(days=days_back)
    start_str = start_dt.strftime("%Y%m%d%H%M")
    end_str = end_dt.strftime("%Y%m%d%H%M")

    logger.info(f"opening_crawler: range {start_str} ~ {end_str}")

    db = SessionLocal()
    inserted = 0
    updated = 0
    skipped = 0
    pages_fetched = 0

    try:
        for page in range(1, max_pages + 1):
            items = _fetch_page(start_str, end_str, page=page)
            pages_fetched = page
            if not items:
                break
            for item in items:
                kwargs = _parse_item_to_kwargs(item)
                if kwargs is None:
                    skipped += 1
                    continue
                if _upsert_opening_result(db, kwargs):
                    inserted += 1
                else:
                    updated += 1
            # 100개 미만 = 마지막 페이지
            if len(items) < 100:
                break
        db.commit()
    except Exception as e:  # noqa: BLE001
        db.rollback()
        logger.error(f"opening_crawler: commit fail {type(e).__name__}: {e}")
        return {
            "ok": False,
            "error": f"{type(e).__name__}: {e}",
            "inserted": inserted,
            "updated": updated,
        }
    finally:
        db.close()

    summary = {
        "ok": True,
        "range": f"{start_str}~{end_str}",
        "pages_fetched": pages_fetched,
        "inserted": inserted,
        "updated": updated,
        "skipped": skipped,
    }
    logger.info(f"opening_crawler: {summary}")
    return summary
