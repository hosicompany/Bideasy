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
import time
from datetime import datetime, timedelta, timezone

import requests
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db import models
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)

_BASE_URL = "https://apis.data.go.kr/1230000/ao/PubDataOpnStdService/getDataSetOpnStdScsbidInfo"
_BSNS_DIV_CONSTRUCTION = "3"  # 공사
_PAGE_SIZE = 999  # API accepts at most 999; 1000 falls back to 10 rows.


def _fetch_page(
    start_dt: str,
    end_dt: str,
    page: int = 1,
    num_rows: int = _PAGE_SIZE,
) -> list[dict]:
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
    last_error = None
    for attempt in range(1, 4):
        try:
            resp = requests.get(_BASE_URL, params=params, timeout=60)
            if 500 <= resp.status_code < 600:
                last_error = RuntimeError(f"HTTP {resp.status_code}")
                if attempt < 3:
                    time.sleep(2 ** (attempt - 1))
                    continue
                raise last_error
            if resp.status_code != 200:
                raise RuntimeError(f"HTTP {resp.status_code}")
            data = resp.json()
            err = data.get("nkoneps.com.response.ResponseError", {})
            if err:
                message = err.get("header", {}).get("resultMsg", "unknown API error")
                raise RuntimeError(f"API error: {message}")
            items = data.get("response", {}).get("body", {}).get("items", []) or []
            return [items] if isinstance(items, dict) else items
        except requests.RequestException as e:
            last_error = RuntimeError(f"{type(e).__name__}: {e}")
            if attempt < 3:
                time.sleep(2 ** (attempt - 1))
                continue
            raise last_error from e
        except RuntimeError:
            raise
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(f"{type(e).__name__}: {e}") from e
    raise last_error or RuntimeError("public API request failed")


def _daily_windows(start_dt: datetime, end_dt: datetime):
    """Split a range into calendar-day windows accepted by the public API."""
    cursor = start_dt
    while cursor <= end_dt:
        day_end = cursor.replace(hour=23, minute=59, second=0, microsecond=0)
        window_end = min(day_end, end_dt)
        yield cursor, window_end
        cursor = (cursor + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )


def _parse_item_to_kwargs(item: dict) -> dict | None:
    """API 응답 item 을 OpeningResult 모델 kwargs 로 변환.

    조달청_나라장터 공공데이터개방표준서비스 응답 스키마:
    - 참가자별로 row 가 분리되어 옴 (한 bid_no 에 N개)
    - opengRank: 개찰 순위 (1 = 최저가)
    - sucsfYn: 'Y' = 적격검사 통과 winner, 'N' = 미통과/검사중
    - fnlSucsfAmt: 최종 낙찰금액 (검사 완료 시 설정)
    - bidprcAmt: 그 참가자의 투찰금액

    낙찰자 row 만 OpeningResult 로 저장 (winner row).
    검사 진행 중인 입찰은 다음 크롤 사이클에 잡힘.
    """
    bid_no_raw = item.get("bidNtceNo")
    ord_raw = item.get("bidNtceOrd")
    if not bid_no_raw:
        return None
    bid_no = f"{bid_no_raw}-{ord_raw or '000'}"

    def _f(v):
        if v in (None, ""):
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    # 낙찰자 판별 — fnlSucsfAmt 우선, 없으면 sucsfYn=Y + bidprcAmt
    fnl_amt = _f(item.get("fnlSucsfAmt"))
    fnl_rate = _f(item.get("fnlSucsfRt"))
    sucsf_yn = (item.get("sucsfYn") or "").strip().upper()
    bid_amt = _f(item.get("bidprcAmt"))
    bid_rate = _f(item.get("bidprcRt"))

    winner_price = None
    winner_rate = None
    winner_company = ""
    if fnl_amt and fnl_amt > 0:
        winner_price = fnl_amt
        winner_rate = fnl_rate
        winner_company = item.get("fnlSucsfCorpNm") or item.get("bidprcCorpNm") or ""
    elif sucsf_yn == "Y" and bid_amt and bid_amt > 0:
        winner_price = bid_amt
        winner_rate = bid_rate
        winner_company = item.get("bidprcCorpNm") or ""
    else:
        # 낙찰자 row 가 아님 (참가자 row 또는 검사 진행중) → skip
        return None

    basic_price = _f(item.get("presmptPrce"))   # 기초금액
    reserved_price = _f(item.get("rsrvtnPrce")) # 예정가격

    # 낙찰률 계산 fallback (기초금액 대비)
    if (not winner_rate or winner_rate <= 0) and basic_price and basic_price > 0:
        winner_rate = round(winner_price / basic_price * 100, 4)

    # Sanity check — 단가계약·데이터오류 등으로 winner/basic 비율이 비정상이면 skip
    # 정상 입찰의 사정률은 거의 항상 70~120% 사이. 그 외는 API 데이터 품질 의심.
    if basic_price and basic_price > 0:
        ratio = winner_price / basic_price
        if ratio < 0.5 or ratio > 1.5:
            logger.warning(
                f"opening_crawler: suspicious ratio for {bid_no} "
                f"(basic={basic_price:,.0f}, winner={winner_price:,.0f}, ratio={ratio:.2%}) — skipped"
            )
            return None

    # 개찰 일시 — opengDate + opengTm 합쳐서 datetime
    parsed_open_dt = None
    od = item.get("opengDate")
    ot = item.get("opengTm") or "00:00"
    if od:
        try:
            parsed_open_dt = datetime.strptime(f"{od} {ot}", "%Y-%m-%d %H:%M")
        except ValueError:
            try:
                parsed_open_dt = datetime.strptime(od, "%Y-%m-%d")
            except ValueError:
                parsed_open_dt = None

    return {
        "bid_no": bid_no,
        "organization": item.get("ntceInsttNm") or item.get("dmndInsttNm") or "",
        "region": "",  # 본 API 에 없음
        "open_date": parsed_open_dt,
        "basic_price": basic_price,
        "reserved_price": reserved_price,
        "bid_method": item.get("bidwinrDcsnMthdNm") or item.get("cntrctCnclsMthdNm") or "",
        "winner_company": winner_company,
        "winner_price": winner_price,
        "winner_rate": winner_rate,
        "participants_count": None,  # 본 API 직접 노출 안 됨 (rank 카운트로 추정 가능)
        "crawled_at": datetime.now(timezone.utc),
    }


def _upsert_opening_result(db: Session, kwargs: dict, seen: set[str]) -> bool:
    """OpeningResult upsert. 반환: 신규 삽입 True / 업데이트 False.

    `seen` 은 이번 크롤 세션 내 처리한 bid_no 집합. DB 조회는 미커밋 행을
    못 봐서, 동일 bid_no 가 응답에 여러 번(참가자 분리) 나오는 경우
    중복 INSERT → IntegrityError 가 발생하므로 set 으로 차단.
    """
    bid_no = kwargs["bid_no"]
    if bid_no in seen:
        # 이미 이 세션에서 처리한 bid_no — skip
        return False
    seen.add(bid_no)

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


def crawl_recent_openings(days_back: int = 2, max_pages: int = 200) -> dict:
    """최근 N일 (기본 2일) 동안 개찰된 공사 결과 일괄 크롤 → DB upsert.

    매일 Celery beat 가 호출. days_back=2 로 안전마진(하루 누락 방지).
    """
    end_dt = datetime.now()
    start_dt = end_dt - timedelta(days=days_back)
    overall_start = start_dt.strftime("%Y%m%d%H%M")
    overall_end = end_dt.strftime("%Y%m%d%H%M")

    logger.info(f"opening_crawler: range {overall_start} ~ {overall_end}")

    db = SessionLocal()
    inserted = 0
    updated = 0
    skipped = 0
    pages_fetched = 0
    seen: set[str] = set()  # 이번 세션 dedupe (API 가 동일 bid_no 를 여러 row 로 반환)

    try:
        for window_start, window_end in _daily_windows(start_dt, end_dt):
            start_str = window_start.strftime("%Y%m%d%H%M")
            end_str = window_end.strftime("%Y%m%d%H%M")
            window_inserted = 0
            window_updated = 0
            window_skipped = 0
            logger.info(f"opening_crawler: window {start_str} ~ {end_str}")
            for page in range(1, max_pages + 1):
                items = _fetch_page(start_str, end_str, page=page)
                pages_fetched += 1
                if not items:
                    break
                for item in items:
                    kwargs = _parse_item_to_kwargs(item)
                    if kwargs is None:
                        window_skipped += 1
                        continue
                    if _upsert_opening_result(db, kwargs, seen):
                        window_inserted += 1
                    else:
                        window_updated += 1
                # 요청 건수 미만 = 마지막 페이지
                if len(items) < _PAGE_SIZE:
                    break
            else:
                raise RuntimeError(
                    f"page limit reached with a full page: {start_str}~{end_str} "
                    f"(max_pages={max_pages})"
                )
            db.commit()
            inserted += window_inserted
            updated += window_updated
            skipped += window_skipped
    except Exception as e:  # noqa: BLE001
        db.rollback()
        logger.error(f"opening_crawler: commit fail {type(e).__name__}: {e}")
        return {
            "ok": False,
            "error": f"{type(e).__name__}: {e}",
            "inserted": inserted,
            "updated": updated,
            "skipped": skipped,
        }
    finally:
        db.close()

    summary = {
        "ok": True,
        "range": f"{overall_start}~{overall_end}",
        "pages_fetched": pages_fetched,
        "inserted": inserted,
        "updated": updated,
        "skipped": skipped,
    }
    logger.info(f"opening_crawler: {summary}")
    return summary
