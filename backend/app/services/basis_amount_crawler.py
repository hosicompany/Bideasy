"""공사 기초금액 수집 — `getBidPblancListInfoCnstwkBsisAmount`.

왜 별도 크롤러인가
------------------
공고 목록 API(143필드)에는 **기초금액이 없다**. `presmptPrce` 는 추정가격(부가세
제외)이고 기초금액은 그 약 1.1 배다. 기초금액은 전용 오퍼레이션이 `bssamt` 로
따로 준다. 경위 전체: docs/PRICE_BASE_DEFECT.md

같은 응답에 **A값 구성요소도 함께** 온다. 그동안 A값은 "어떤 조달청
OpenAPI 에도 없다"고 보고 익스텐션 크라우드소싱 → 첨부 파싱의 3-tier 로
모으려 했는데(실적: 35,503건 중 3건), 사실은 API 에 있었다.

⚠️ 커버리지는 100% 가 아니다 (실측 80.1%)
-----------------------------------------
기초금액 공고 자체가 없는 건이 있다(최저가낙찰제 25%·제한적최저가 8% 수준).
못 채운 건은 `basis_amount` 를 NULL 로 두고 **추정하지 않는다** —
소비 쪽에서 "기초금액 미확인"으로 다뤄 안전 판정을 보류한다.

⛔ `basic_price` 에 덮어쓰지 말 것 — 확인된 건만 덮으면 한 컬럼에 또 두 기준이
섞인다. 그게 이번 사고의 원인이다.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta

import requests
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.db import models
from app.db.session import SessionLocal

logger = get_logger(__name__)

_URL = ("https://apis.data.go.kr/1230000/ad/BidPublicInfoService/"
        "getBidPblancListInfoCnstwkBsisAmount")
_PAGE_SIZE = 500

# A값 구성요소 — 사후정산 비목. 합계가 곧 A값이다.
# (국민연금·건강보험·노인장기요양·퇴직공제부금·산업안전보건관리비·안전관리비·
#  품질관리비·환경보전비·안전점검비·하도급대금지급보증수수료)
A_VALUE_KEYS = (
    "npnInsrprm",                  # 국민연금보험료
    "mrfnHealthInsrprm",           # 국민건강보험료
    "odsnLngtrmrcprInsrprm",       # 노인장기요양보험료
    "rtrfundNon",                  # 퇴직공제부금비
    "industSftyHelthMngcst",       # 산업안전보건관리비
    "sftyMngcst",                  # 안전관리비
    "qltyMngcst",                  # 품질관리비
    "envCnsrvcst",                 # 환경보전비
    "sftyChckMngcst",              # 안전점검비
    "scontrctPayprcePayGrntyFee",  # 하도급대금지급보증서 발급수수료
)


def _f(v) -> float:
    if v in (None, ""):
        return 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _parse_dt(v: str | None) -> datetime | None:
    if not v:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(v, fmt)
        except ValueError:
            continue
    return None


def fetch_day(day: str) -> list[dict]:
    """하루치 전량. 실패는 빈 리스트 — 한 날짜 실패가 배치를 끊지 않는다."""
    out: list[dict] = []
    page = 1
    while True:
        try:
            r = requests.get(_URL, params={
                "serviceKey": settings.PUBLIC_DATA_KEY,
                "numOfRows": _PAGE_SIZE, "pageNo": page, "type": "json",
                "inqryDiv": 1, "inqryBgnDt": f"{day}0000", "inqryEndDt": f"{day}2359",
            }, timeout=60)
            body = r.json()["response"]["body"]
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[basis_amount] {day} p{page} 조회 실패: {type(e).__name__}: {e}")
            return out
        items = body.get("items") or []
        if isinstance(items, dict):
            items = items.get("item") or []
        out.extend(items)
        total = int(body.get("totalCount") or 0)
        if not items or len(out) >= total:
            return out
        page += 1
        time.sleep(0.2)


def parse_item(item: dict) -> dict | None:
    """API item → Notice 갱신 kwargs. 기초금액이 없으면 None(저장 안 함)."""
    bid_no_raw = item.get("bidNtceNo")
    if not bid_no_raw:
        return None
    bss = _f(item.get("bssamt"))
    if bss <= 0:
        return None

    applicable = (item.get("bidPrceCalclAYn") or "").strip().upper() or None
    a_total = int(sum(_f(item.get(k)) for k in A_VALUE_KEYS))

    return {
        "bid_no": f"{bid_no_raw}-{item.get('bidNtceOrd') or '000'}",
        "basis_amount": bss,
        "basis_amount_at": _parse_dt(item.get("bssamtOpenDt") or item.get("inptDt")),
        "prdprc_range_bgn": _f(item.get("rsrvtnPrceRngBgnRate")) or None,
        "prdprc_range_end": _f(item.get("rsrvtnPrceRngEndRate")) or None,
        "a_value": a_total,
        "a_value_applicable": applicable,
    }


def apply_to_notice(db: Session, kwargs: dict) -> str:
    """기존 Notice 에 반영. 반환: updated | unchanged | no_notice.

    공고가 아직 수집 안 됐으면 아무것도 하지 않는다 — 기초금액만 있는 유령
    행을 만들면 검색·계산이 제목도 마감도 없는 공고를 보게 된다.
    """
    n = db.query(models.Notice).filter(models.Notice.bid_no == kwargs["bid_no"]).first()
    if n is None:
        return "no_notice"

    changed = False
    for col in ("basis_amount", "basis_amount_at",
                "prdprc_range_bgn", "prdprc_range_end", "a_value_applicable"):
        v = kwargs.get(col)
        if v is not None and getattr(n, col, None) != v:
            setattr(n, col, v)
            changed = True

    # A값은 tier0(API) 가 최우선이다. 다른 tier 가 채운 값이 있어도 덮는다 —
    # 조달청이 공고에 실어 준 값이 크라우드소스·첨부파싱보다 정확하다.
    a_new = kwargs.get("a_value")
    if a_new is not None and (n.a_value or 0) != a_new:
        n.a_value = a_new
        n.a_value_source = "tier0"
        changed = True
    elif a_new is not None and n.a_value_source != "tier0":
        n.a_value_source = "tier0"
        changed = True

    return "updated" if changed else "unchanged"


def crawl_recent(days_back: int = 3) -> dict:
    """최근 N일 기초금액 공고 수집 → Notice 갱신.

    days_back 기본 3 — 기초금액은 개찰 직전에 공개되는 경우가 있어 하루만 보면
    놓친다. 물량이 하루 150~200건이라 겹쳐 읽어도 부담이 없다(멱등).
    """
    end = datetime.now()
    start = end - timedelta(days=days_back)
    db = SessionLocal()
    stats = {"fetched": 0, "parsed": 0, "updated": 0, "unchanged": 0, "no_notice": 0}
    try:
        d = start.date()
        while d <= end.date():
            items = fetch_day(d.strftime("%Y%m%d"))
            stats["fetched"] += len(items)
            for it in items:
                kw = parse_item(it)
                if kw is None:
                    continue
                stats["parsed"] += 1
                try:
                    stats[apply_to_notice(db, kw)] += 1
                except Exception as e:  # noqa: BLE001
                    # 한 건의 결함이 배치를 끊지 않는다
                    logger.warning(f"[basis_amount] 반영 실패 {kw['bid_no']}: {e}")
            db.commit()
            d += timedelta(days=1)
    except Exception as e:  # noqa: BLE001
        db.rollback()
        logger.error(f"[basis_amount] 배치 실패: {type(e).__name__}: {e}", exc_info=True)
        stats["error"] = f"{type(e).__name__}: {e}"
    finally:
        db.close()
    logger.info(f"[basis_amount] {stats}")
    return stats
