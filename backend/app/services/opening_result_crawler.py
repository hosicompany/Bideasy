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

import hashlib
import json
import logging
import time
from datetime import date as date_type
from datetime import datetime, timedelta, timezone

import requests
from sqlalchemy.exc import (
    InterfaceError,
    InternalError,
    OperationalError,
    PendingRollbackError,
    ProgrammingError,
)
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db import models
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)

_BASE_URL = "https://apis.data.go.kr/1230000/ao/PubDataOpnStdService/getDataSetOpnStdScsbidInfo"
_BSNS_DIV_CONSTRUCTION = "3"  # 공사
_PAGE_SIZE = 999  # API accepts at most 999; 1000 falls back to 10 rows.

# `participants_count` 와 `crawled_at` 은 결과 자체가 아니라 수집 상태다. 이 둘이
# 바뀔 때마다 outcome revision 을 만들면 매일 같은 개찰 결과가 새 정정처럼
# 쌓인다. 아래 필드만 authoritative opening-outcome payload 로 고정한다.
_OUTCOME_FIELDS = (
    "bid_no",
    "organization",
    "open_date",
    "basic_price",
    "reserved_price",
    "lower_limit_rate",
    "bid_method",
    "winner_company",
    "winner_price",
    "winner_rate",
)
_OPENING_SOURCE_TYPE = "G2B_OPENING_RESULT_ITEM"
_UPSERT_INSERTED = "inserted"
_UPSERT_UPDATED = "updated"
_UPSERT_UNCHANGED = "unchanged"

#: 저장 실패를 **구조적 고장**으로 볼 예외들 — 테이블·컬럼 부재, 연결 단절.
#: 1건만 나와도 전 건에 해당하므로 "몇 건이 실패했나"로 판정하면 안 된다.
#: 나머지(값 범위 초과 등)는 그 건만의 데이터 결함이다.
#: `InterfaceError`(pgbouncer 유휴 종료·SSL 오류)와 `PendingRollbackError`
#: (앞 건의 rollback 실패 후속)가 빠지면, 연결이 통째로 끊긴 상황이 "데이터
#: 결함"으로 분류돼 이 검출기가 존재 이유인 자리에서 침묵한다.
_STRUCTURAL_DB_ERRORS = (
    OperationalError, ProgrammingError, InternalError,
    InterfaceError, PendingRollbackError,
)


def _json_safe(value):
    """Return a stable JSON value without mutating the public-API item."""
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, date_type):
        return value.isoformat()
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _content_hash(value: object) -> str:
    payload = json.dumps(
        _json_safe(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _effective_outcome_payload(
    kwargs: dict,
    existing: models.OpeningResult | None,
) -> tuple[dict, dict]:
    """Build projection values plus their canonical JSON representation.

    The public API sometimes omits an optional field on a later crawl.  Existing
    crawler semantics preserve the last known non-null value, so a transient
    omission cannot erase a confirmed reserved price or lower-limit rate.
    """
    projection: dict = {}
    for field in _OUTCOME_FIELDS:
        incoming = kwargs.get(field)
        if existing is not None:
            current = getattr(existing, field)
            if incoming is None or (
                isinstance(incoming, str) and not incoming and current
            ):
                incoming = current
        projection[field] = incoming
    return projection, _json_safe(projection)


def _persist_raw_snapshot(
    db: Session,
    *,
    item: dict,
    bid_no: str,
    captured_at: datetime,
) -> str:
    """Persist one accepted API item by content address, idempotently."""
    raw_payload = _json_safe(item)
    artifact_hash = _content_hash(raw_payload)
    snapshot_hash = _content_hash(
        {"source_type": _OPENING_SOURCE_TYPE, "artifact_hash": artifact_hash}
    )
    existing = db.get(models.RawSourceSnapshot, snapshot_hash)
    if existing is None:
        snapshot = models.RawSourceSnapshot(
            snapshot_hash=snapshot_hash,
            source_type=_OPENING_SOURCE_TYPE,
            source_uri=_BASE_URL,
            captured_at=captured_at,
            as_of_cutoff=captured_at,
            artifact_hash=artifact_hash,
            raw_payload=raw_payload,
            attributes={
                "bid_no": bid_no,
                "business_division": _BSNS_DIV_CONSTRUCTION,
            },
            created_at=captured_at,
        )
        db.add(snapshot)
        # OpeningResultRevision references this PK but there is no ORM
        # relationship for SQLAlchemy to infer insert order. Flush the parent
        # explicitly so immediate PostgreSQL/SQLite foreign keys cannot see the
        # revision first and roll back the whole crawl window.
        db.flush([snapshot])
    elif (
        existing.source_type != _OPENING_SOURCE_TYPE
        or existing.artifact_hash != artifact_hash
        or _content_hash(existing.raw_payload) != artifact_hash
    ):
        # A SHA-256 collision or manual row corruption must never be hidden by
        # treating the snapshot as an idempotent duplicate.
        raise RuntimeError(f"raw snapshot hash collision: {snapshot_hash}")
    return snapshot_hash


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

    # ⚠️ `presmptPrce` 는 추정가격(부가세 제외)이지 기초금액이 아니다.
    # 기초금액은 `bssAmt` 로 따로 온다(실측 2,000건 중 1,998건 제공).
    # 예전에 presmptPrce 를 basic_price 로 저장한 탓에 정적 개찰 파일(기초금액
    # 기준)과 기준이 섞여, 사정률이 1.10 으로 나오고 무효율이 99% 로 튀었다.
    # 자세한 경위: docs/PRICE_BASE_DEFECT.md
    basic_price = _f(item.get("bssAmt"))        # 기초금액 (부가세 포함)
    reserved_price = _f(item.get("rsrvtnPrce")) # 예정가격
    lower_limit_rate = _f(item.get("sucsfLwstlmtRt"))  # 낙찰하한율 — 레코드별 제공

    # 기초금액이 없으면 추정가격으로 대체하지 않는다. 대체하면 기준이 다시
    # 섞이고, 그 행은 조용히 9% 낮은 가격으로 판정된다.
    if not basic_price or basic_price <= 0:
        logger.warning(f"opening_crawler: bssAmt 없음 — skipped ({bid_no})")
        return None

    # 낙찰률 fallback — **예정가격 대비**로 계산한다.
    # API 의 fnlSucsfRt·bidprcRt 도 예정가격 기준이고, 정적 개찰 파일의
    # winner_rate 도 예정가격 기준이다(실측 확인). 여기서만 기초금액 대비로
    # 계산하면 결측 건에서 기준이 갈린다.
    if (not winner_rate or winner_rate <= 0) and reserved_price and reserved_price > 0:
        winner_rate = round(winner_price / reserved_price * 100, 4)

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
        "lower_limit_rate": lower_limit_rate or None,
        "bid_method": item.get("bidwinrDcsnMthdNm") or item.get("cntrctCnclsMthdNm") or "",
        "winner_company": winner_company,
        "winner_price": winner_price,
        "winner_rate": winner_rate,
        # 참여사수는 여기서 못 채운다 — item 하나는 참가자 한 명이라 행 수를
        # 세야 한다. 창 전체를 훑은 뒤 `_apply_participant_counts` 가 채운다.
        # (outcome revision 대상에서 제외돼 `_apply_participant_counts` 만 갱신한다)
        "participants_count": None,
        "crawled_at": datetime.now(timezone.utc),
    }


def _parse_participant_kwargs(item: dict, stats: dict | None = None) -> dict | None:
    """API 응답 item 을 OpeningParticipant kwargs 로 변환.

    `_parse_item_to_kwargs` 가 낙찰자 행만 남기고 버리는 것과 달리, 여기서는
    낙찰자를 포함한 **모든 참가자 행**을 줍는다(낙찰자도 참가자다). 등수
    재구성(설계 §4-3)에 필요한 건 투찰가이므로 `bidprcAmt` 없는 행은 버린다.
    """
    bid_no_raw = item.get("bidNtceNo")
    if not bid_no_raw:
        return None
    bid_no = f"{bid_no_raw}-{item.get('bidNtceOrd') or '000'}"

    def _f(v):
        if v in (None, ""):
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    bid_amt = _f(item.get("bidprcAmt"))
    if not bid_amt or bid_amt <= 0:
        return None

    # `opengRank` 는 **유효 투찰(낙찰하한선 이상)에만** 부여된다 — 값이 비어
    # 있다는 건 그 투찰이 무효라는 뜻이다(2026-08-11 실측: 전체의 47.6%).
    #
    # 그래서 세 경우를 **갈라 세야** 한다. 뭉치면 API 가 필드명을 바꿨을 때
    # 전 참가자가 조용히 "무효"로 둔갑하는데, 무효는 평소에도 큰 수라 증가가
    # 묻힌다. `rank_field_missing` 이 그 사고를 가리키는 유일한 신호다.
    rank = None
    if stats is not None:
        stats["rows"] = stats.get("rows", 0) + 1
    if "opengRank" not in item:
        # 스키마 변경 의심 — 필드 자체가 응답에 없다
        if stats is not None:
            stats["rank_field_missing"] = stats.get("rank_field_missing", 0) + 1
    elif item["opengRank"] in (None, ""):
        # 정상 — 무효 투찰이라 API 가 순위를 주지 않았다
        if stats is not None:
            stats["rank_absent"] = stats.get("rank_absent", 0) + 1
    else:
        try:
            rank = int(item["opengRank"])
        except (TypeError, ValueError):
            # 형식 변경 의심 — 값은 있는데 정수가 아니다
            if stats is not None:
                stats["rank_unparsed"] = stats.get("rank_unparsed", 0) + 1

    return {
        "bid_no": bid_no,
        "rank": rank,
        # 병합 키의 일부라 **정규화가 필수**다. 후행 공백 하나만 붙어도 같은
        # 업체가 별개 행이 되고, 삭제 경로가 없어 그 중복은 영구히 남는다
        # (실측 2026-08-12: 앞뒤 공백 212행 / 466,850).
        "company": (item.get("bidprcCorpNm") or "").strip(),
        "bid_price": int(bid_amt),
        "bid_rate": _f(item.get("bidprcRt")),
        "sucsf_yn": (item.get("sucsfYn") or "").strip().upper() or None,
    }


def _load_registered_bid_nos(db: Session) -> tuple[set[str], bool]:
    """모의투찰에 등록된 bid_no 집합 — 참가자 저장 범위(설계 §P4).

    전수 저장은 하루 169k행 규모라 함정이다. 등록분만 담으면 데이터량이
    수십분의 1로 떨어지면서 얻을 건 다 얻는다. 실패해도 본 크롤(낙찰 결과
    적재)을 막지 않는다 — 참가자는 부가 데이터다.

    **다만 실패했다는 사실은 반드시 위로 올린다**(`ok` 플래그). 조용히 빈
    집합을 돌려주면 그 회차 참가자 수집이 통째로 생략되는데, 크롤은 초록불이고
    화면은 "참가자 데이터 대기"와 똑같아서 며칠이 지나도 아무도 모른다.
    """
    try:
        return {row[0] for row in db.query(models.MockBid.bid_no).distinct().all()}, True
    except Exception as e:  # noqa: BLE001
        # rollback 이 없으면 PostgreSQL 은 트랜잭션을 abort 상태로 두고, 이후
        # 본 크롤의 모든 쿼리가 InFailedSqlTransaction 으로 죽는다 —
        # "실패해도 본 크롤을 막지 않는다"는 이 함수의 약속이 깨진다.
        db.rollback()
        logger.error(f"opening_crawler: 등록 bid_no 조회 실패 — 참가자 저장 생략: {e}")
        return set(), False


def _save_participants(db: Session, by_bid: dict[str, list[dict]]) -> dict:
    """공고 단위로 참가자 행을 **병합**한다. 삭제하지 않는다.

    **왜 삭제-재삽입을 버렸나**: 그 방식은 부분 응답이 완전 집합을 덮어쓰는
    구조라 "행 수가 줄면 보류" 가드가 필요했는데, 그 가드는 정기 스케줄에서
    원리적으로 동작할 수 없었다. `days_back=2` + 하루 1회 크롤이면 한 공고는
    **정확히 2회만** 조회되고(1회차는 기존 행이 없어 판정 자체가 없다) 2회차의
    경과는 **항상 24시간**이다. 즉 관측 가능한 경과가 한 값뿐이라 어떤 시효를
    골라도 "항상 채택"(가드 부재) 아니면 "항상 보류"(영구 고착) 둘 중 하나가
    된다 — 한 번 보류한 뒤 스스로 낫는 값은 존재하지 않는다. 실제로 3일로
    뒀을 땐 도달 불가였고, 20시간으로 낮췄더니 가드가 통째로 무력해졌다.

    병합은 그 딜레마를 없앤다. 축소가 **구조적으로 불가능**해지므로 가드도
    시효도 필요 없다 — 이 코드에서 회귀는 늘 분기를 더한 자리에서 났다.

    키는 `(company, bid_price)` 다. 같은 업체가 한 공고에 두 번 투찰할 수 없다.
    `rank`·`sucsf_yn` 은 적격검사 진행 중 바뀌므로(N→Y) 키가 아니라 **갱신
    대상**이다 — 삭제-재삽입의 원래 명분이었던 그 갱신은 그대로 유지된다.

    공고 단위 커밋 — 1건 결함이 나머지 공고의 참가자까지 날리지 않게.
    """
    saved_bids = 0
    written_rows = 0
    errors = 0
    structural_errors = 0
    final_counts: dict[str, int] = {}
    now = datetime.now(timezone.utc)
    for bid_no, rows in by_bid.items():
        # 같은 응답 안의 중복 행 방어 (신뢰하되 확인)
        uniq: dict[tuple, dict] = {}
        for r in rows:
            uniq[(r["company"], r["bid_price"])] = r
        try:
            existing = {
                (p.company, p.bid_price): p
                for p in db.query(models.OpeningParticipant)
                .filter(models.OpeningParticipant.bid_no == bid_no)
                .all()
            }
            written = 0
            for key, r in uniq.items():
                row = existing.get(key)
                if row is None:
                    db.add(models.OpeningParticipant(**r, crawled_at=now))
                    written += 1
                    continue
                if (row.rank != r["rank"] or row.sucsf_yn != r["sucsf_yn"]
                        or row.bid_rate != r["bid_rate"]):
                    row.rank = r["rank"]
                    row.sucsf_yn = r["sucsf_yn"]
                    row.bid_rate = r["bid_rate"]
                    # 실제로 바뀐 행만 시각을 새로 찍는다. 무조건 갱신하면
                    # 재크롤마다 전 행이 UPDATE 돼 dead tuple 이 쌓이고,
                    # "마지막으로 실제 바뀐 시점"이라는 신호도 잃는다.
                    row.crawled_at = now
                    written += 1
            db.commit()
            saved_bids += 1
            written_rows += written
            # 병합 후 실제 행 수. `OpeningResult.participants_count` 를 이 값으로
            # 맞춰야 두 저장소가 같은 말을 한다(따로 세면 언젠가 갈라진다).
            final_counts[bid_no] = len(existing | uniq)
        except _STRUCTURAL_DB_ERRORS as e:
            # 테이블·컬럼 부재, 연결 단절 — 1건만 나와도 전 건에 해당하는 고장이다.
            # 표본 수로 "전면 실패"를 가리려 하면 소표본에서 늘 오판한다.
            db.rollback()
            errors += 1
            structural_errors += 1
            logger.error(f"opening_crawler: 참가자 저장 구조적 실패 {bid_no}: "
                         f"{type(e).__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            # 데이터 결함(값 범위 초과·제약 위반 등) — 그 건만의 문제다
            db.rollback()
            errors += 1
            logger.warning(f"opening_crawler: 참가자 저장 실패 {bid_no}: {type(e).__name__}: {e}")
    return {
        "participant_bids": saved_bids,
        "participant_rows_changed": written_rows,
        "participant_errors": errors,
        "participant_structural_errors": structural_errors,
        "participant_final_counts": final_counts,
    }


def _apply_participant_counts(db: Session, counts: dict[str, int]) -> int:
    """창 안에서 센 참가자 행 수를 `OpeningResult.participants_count` 에 반영.

    **왜 따로 도나**: API 는 참가자 한 명당 item 하나를 주므로 참여사수는
    "그 공고의 행이 몇 개였나"다. item 하나만 보는 `_parse_item_to_kwargs` 는
    셀 수 없고, `_upsert_opening_result` 의 권위 outcome payload 에서도 의도적으로
    제외한다. 참가자 수 정정이 낙찰 결과 정정 revision 으로 기록되면 안 된다.

    ⚠️ 이 값은 **그 조회 창에서 API 가 준 행 수**다. 창 전체를 다 훑었을
    때만 참이며, 페이지 상한에 걸리면 크롤이 RuntimeError 로 멈추므로
    잘린 채 저장되지는 않는다.

    추가 API 호출은 0 이다 — 이미 받아 온 응답을 세기만 한다.

    ⚠️ **축소 가드를 두지 않는다.** 한때 참가자 행과 같은 규칙을 적용했지만,
    여기엔 자기 치유 경로가 없어 한 번 부푼 값이 영영 안 내려갔다. master 는
    가드가 없어 다음 크롤에 스스로 교정됐는데 그 자기 교정을 없앤 셈이었다.
    등록 공고는 아래 `participant_final_counts`(병합 후 실제 행 수)로 덮으므로
    부분 응답에 흔들리지 않고, 미등록 공고는 이 창 집계가 유일한 소스다.
    """
    if not counts:
        return 0
    updated = 0
    for bid_no, cnt in counts.items():
        row = db.query(models.OpeningResult).filter(
            models.OpeningResult.bid_no == bid_no
        ).first()
        if row is None or cnt <= 0:
            continue
        if row.participants_count != cnt:
            row.participants_count = cnt
            updated += 1
    return updated


def _upsert_opening_result(
    db: Session,
    kwargs: dict,
    seen: set[tuple[str, str]],
    *,
    source_item: dict | None = None,
) -> str:
    """OpeningResult upsert. 반환: inserted / updated / unchanged.

    `OpeningResult` 는 현재값 projection 이고 `OpeningResultRevision` 이 정본
    변경 이력이다. 같은 결과를 다시 받으면 snapshot/revision/projection 모두
    그대로이며, 권위 필드가 달라졌을 때만 새 revision 을 이전 revision 에
    연결하고 projection 을 갱신한다.

    `seen` 은 `(bid_no, outcome_content_hash)` 집합이다. 참가자별로 반복된 같은
    낙찰결과는 막되, 한 응답 안에서 실제 정정 결과가 함께 온 경우까지 버리지
    않는다. `source_item` 은 실제 크롤 경로에서 항상 raw API item 이며, 직접
    호출하는 레거시 코드에는 kwargs 를 원문 대용으로 허용한다.
    """
    bid_no = kwargs["bid_no"]
    existing = db.query(models.OpeningResult).filter(
        models.OpeningResult.bid_no == bid_no
    ).first()
    projection, payload = _effective_outcome_payload(kwargs, existing)
    content_hash = _content_hash(payload)
    seen_key = (bid_no, content_hash)
    if seen_key in seen:
        # 이미 이 세션에서 처리한 동일 결과 — skip
        return _UPSERT_UNCHANGED
    seen.add(seen_key)

    captured_at = kwargs.get("crawled_at") or datetime.now(timezone.utc)
    latest_revision = (
        db.query(models.OpeningResultRevision)
        .filter(models.OpeningResultRevision.bid_no == bid_no)
        .order_by(models.OpeningResultRevision.revision_no.desc())
        .first()
    )
    stored_payload = None
    if existing is not None:
        _, stored_payload = _effective_outcome_payload({}, existing)
    projection_changed = stored_payload is None or _content_hash(stored_payload) != content_hash

    inserted = existing is None
    if inserted:
        projection_kwargs = {
            field: projection[field]
            for field in _OUTCOME_FIELDS
        }
        # 이 API 는 지역을 주지 않으므로 region 은 outcome content hash 에 넣지
        # 않는다. 삽입 시 호환 필드만 채우고, 후속 크롤이 다른 소스의 지역값을
        # 정정으로 오인하거나 빈 문자열로 지우지 않게 한다.
        projection_kwargs["region"] = kwargs.get("region")
        projection_kwargs["participants_count"] = kwargs.get("participants_count")
        projection_kwargs["crawled_at"] = captured_at
        existing = models.OpeningResult(**projection_kwargs)
        db.add(existing)
        # OpeningResultRevision.bid_no has a FK to this projection.  Flush just
        # the new projection so the revision can be inserted in the same txn.
        db.flush([existing])
    elif projection_changed:
        for field in _OUTCOME_FIELDS:
            if field != "bid_no":
                setattr(existing, field, projection[field])
        existing.crawled_at = captured_at

    # A legacy projection can exist without lineage.  Its first post-migration
    # crawl creates revision 1 even if the value itself did not change.  After
    # that, identical content is a strict no-op.  A→B→A still creates revision
    # 3 because the current head (B), not the historic hash set, is compared.
    revision_appended = (
        latest_revision is None or latest_revision.content_hash != content_hash
    )
    if revision_appended:
        snapshot_hash = _persist_raw_snapshot(
            db,
            item=source_item if source_item is not None else kwargs,
            bid_no=bid_no,
            captured_at=captured_at,
        )
        revision_no = 1 if latest_revision is None else latest_revision.revision_no + 1
        revision_id = _content_hash({
            "bid_no": bid_no,
            "revision_no": revision_no,
            "content_hash": content_hash,
            "supersedes_revision_id": latest_revision.id if latest_revision else None,
        })
        db.add(models.OpeningResultRevision(
            id=revision_id,
            bid_no=bid_no,
            revision_no=revision_no,
            source_snapshot_hash=snapshot_hash,
            content_hash=content_hash,
            payload=payload,
            supersedes_revision_id=latest_revision.id if latest_revision else None,
            observed_at=captured_at,
            created_at=captured_at,
        ))

    if inserted:
        return _UPSERT_INSERTED
    if projection_changed or revision_appended:
        return _UPSERT_UPDATED
    return _UPSERT_UNCHANGED


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
    # `updated` 는 기존 모니터링 계약상 "신규가 아닌 winner row" 수다. 실제
    # 권위 필드 정정 수는 `corrected` 로 따로 내보내 호환성과 의미를 둘 다 지킨다.
    updated = 0
    corrected = 0
    unchanged = 0
    skipped = 0
    pages_fetched = 0
    # API 가 동일 bid_no 를 참가자별 여러 행으로 반복한다. 결과 content hash 까지
    # 함께 봐야 동일 결과만 dedupe 하고 실제 정정은 놓치지 않는다.
    seen: set[tuple[str, str]] = set()

    # 참가자 저장 대상 = 모의투찰 등록 공고만 (설계 §P4 — 전수 저장 금지).
    # API 는 참가자별로 row 를 쪼개 주므로, 낙찰자 판별과 별개로 여기서 줍는다.
    registered_bid_nos, scope_ok = _load_registered_bid_nos(db)
    participants_by_bid: dict[str, list[dict]] = {}
    parse_stats: dict[str, int] = {}
    total_items = 0
    counted = 0

    try:
        for window_start, window_end in _daily_windows(start_dt, end_dt):
            start_str = window_start.strftime("%Y%m%d%H%M")
            end_str = window_end.strftime("%Y%m%d%H%M")
            window_inserted = 0
            window_updated = 0
            window_corrected = 0
            window_unchanged = 0
            window_skipped = 0
            # 참여사수 = 이 창에서 그 공고로 온 참가자 행 수. 창 단위로 세고
            # 창 단위로 반영한다(창을 넘겨 누적하면 재크롤 겹침에서 부풀어 오른다).
            # 참여사수는 **저장과 같은 키로** 센다. raw 행을 그냥 더하면 API 가
            # 같은 행을 두 번 준 날(페이지 경계에서 정렬이 흔들리면 999행 ×
            # 수백 페이지 규모에서 실재하는 사고 — dedup 을 넣은 이유가 그것이다)
            # `participants_count` 만 부풀어 `opening_participants` 행 수와
            # 영구히 어긋난다. 두 저장소가 서로 다른 말을 하게 된다.
            window_keys: dict[str, set] = {}
            logger.info(f"opening_crawler: window {start_str} ~ {end_str}")
            for page in range(1, max_pages + 1):
                items = _fetch_page(start_str, end_str, page=page)
                pages_fetched += 1
                total_items += len(items)
                if not items:
                    break
                for item in items:
                    p = _parse_participant_kwargs(item, parse_stats)
                    if p:
                        # 세는 건 전 공고, 저장은 등록 공고만(설계 §P4).
                        window_keys.setdefault(p["bid_no"], set()).add(
                            (p["rank"], p["company"], p["bid_price"]))
                        if p["bid_no"] in registered_bid_nos:
                            participants_by_bid.setdefault(p["bid_no"], []).append(p)
                    kwargs = _parse_item_to_kwargs(item)
                    if kwargs is None:
                        window_skipped += 1
                        continue
                    action = _upsert_opening_result(
                        db, kwargs, seen, source_item=item
                    )
                    # bool 처리는 이 private helper 를 monkeypatch 하는 오래된
                    # 회귀 테스트와의 호환용이다. 실제 구현은 세 상태 문자열만 준다.
                    if action == _UPSERT_INSERTED or action is True:
                        window_inserted += 1
                    else:
                        # 기존 summary 의 updated 의미를 보존한다. 대시보드/로그의
                        # 장기 시계열이 배포 날 갑자기 0으로 꺾이지 않게 한다.
                        window_updated += 1
                    if action == _UPSERT_UPDATED:
                        window_corrected += 1
                    elif action != _UPSERT_INSERTED and action is not True:
                        window_unchanged += 1
                # 요청 건수 미만 = 마지막 페이지
                if len(items) < _PAGE_SIZE:
                    break
            else:
                raise RuntimeError(
                    f"page limit reached with a full page: {start_str}~{end_str} "
                    f"(max_pages={max_pages})"
                )
            # 창 집계는 **전 공고**를 채운다. 등록 공고는 참가자 저장이 끝난 뒤
            # 실제 행 수로 덮으므로(아래) 순서상 그쪽이 이긴다.
            #
            # ⚠️ 여기서 등록 공고를 미리 빼면 안 된다. 저장이 실패한 공고는
            # `final_counts` 에도 안 들어가서 **어느 경로에서도 안 채워지고**,
            # 2일 창을 벗어나면 영영 NULL 로 남는다(공개 SSR·통계에서 통째로
            # 빠진다). master 는 창 집계가 전 공고를 채워 그 구멍이 없었다.
            counted += _apply_participant_counts(
                db, {b: len(keys) for b, keys in window_keys.items()})
            db.commit()
            inserted += window_inserted
            updated += window_updated
            corrected += window_corrected
            unchanged += window_unchanged
            skipped += window_skipped
    except Exception as e:  # noqa: BLE001
        db.rollback()
        logger.error(f"opening_crawler: commit fail {type(e).__name__}: {e}")
        return {
            "ok": False,
            "error": f"{type(e).__name__}: {e}",
            "inserted": inserted,
            "updated": updated,
            "corrected": corrected,
            "unchanged": unchanged,
            "skipped": skipped,
        }
    finally:
        db.close()

    # 참가자 저장 — 본 크롤 커밋이 전부 끝난 뒤 별도 세션에서 공고 단위 커밋.
    # 실패해도 낙찰 결과 적재를 되돌리지 않는다(부가 데이터).
    p_summary = {"participant_bids": 0, "participant_rows_changed": 0,
                 "participant_errors": 0, "participant_structural_errors": 0,
                 "participant_final_counts": {}}
    if participants_by_bid:
        pdb = SessionLocal()
        try:
            p_summary = _save_participants(pdb, participants_by_bid)
            # 등록 공고의 참여사수 = 병합 후 실제 참가자 행 수. 두 저장소가 같은
            # 소스를 보게 해야 "행 수는 5인데 화면은 12"가 나오지 않는다.
            applied = _apply_participant_counts(
                pdb, p_summary.pop("participant_final_counts"))
            pdb.commit()
            counted += applied
        except Exception as e:  # noqa: BLE001
            # ⚠️ 여기는 한 번에 커밋하므로 실패하면 **그 배치 전부**가 소실된다.
            # `counted` 를 커밋 뒤에 더하는 것도 그래서다 — 앞서 커밋 전에 더했다가
            # "아무것도 저장 안 됐는데 숫자는 성공"으로 보고될 뻔했다.
            # 창 집계가 이미 전 공고를 채워 뒀으므로 값이 통째로 비지는 않는다.
            pdb.rollback()
            logger.error(f"opening_crawler: 참여사수 반영 실패: {type(e).__name__}: {e}")
        finally:
            pdb.close()

    # 참가자 수집 고장을 성공으로 삼키면 정상 화면과 완전 고장 화면이 똑같아진다
    # (설계 §9 원칙). 다만 **건수로 판정하지 않는다** — 이 검출기는 그 방식으로
    # 두 번 틀렸다. "저장 0건"으로 잡으니 정상적인 축소 보류가 고장이 됐고,
    # 분모를 대상 수로 잡으니 시도조차 안 한 건이 섞여 진짜 고장이 초록불이 됐다.
    # 남은 기준 셋은 전부 건수와 무관하다 — 조회 실패 / 구조적 예외 / 파싱 전멸.
    parsed_rows = parse_stats.get("rows", 0)
    field_missing = parse_stats.get("rank_field_missing", 0)
    # API 가 행을 줬는데 참가자가 한 행도 안 나왔다 = 가격 필드명이 바뀐 것이다.
    # `inserted or updated` 를 조건에 걸면 안 된다 — `bidprcAmt` 는 낙찰자 판별
    # 에도 쓰여서 그 필드가 바뀌면 본 크롤도 함께 죽고, 그러면 이 검출기가
    # 정작 그 사고에서 침묵한다(테스트로 확인).
    parse_dead = bool(total_items and parsed_rows == 0)
    # 순위 필드 전멸 = 등수 지표가 통째로 죽는다(전원이 '무효'로 둔갑해 안 보인다)
    rank_field_dead = bool(parsed_rows and field_missing == parsed_rows)
    structural = p_summary["participant_structural_errors"] > 0
    participant_ok = scope_ok and not (structural or parse_dead or rank_field_dead)
    if not participant_ok:
        logger.error(
            f"opening_crawler: 참가자 수집 고장 — scope_ok={scope_ok} "
            f"structural={structural} parse_dead={parse_dead} "
            f"rank_field_dead={rank_field_dead} "
            f"(items={total_items} parsed={parsed_rows} field_missing={field_missing})"
        )
    elif p_summary["participant_errors"]:
        logger.warning(
            f"opening_crawler: 참가자 저장 실패 {p_summary['participant_errors']}건 "
            f"(대상 {len(participants_by_bid)}공고) — 반복되면 원인을 확인할 것"
        )

    summary = {
        "ok": True,
        "participant_ok": participant_ok,
        "participant_scope_ok": scope_ok,
        "participant_targets": len(participants_by_bid),
        # `rank_absent` 는 무효 투찰이라 **평소에도 큰 수**다(실측 47.6%) — 이걸로
        # 이상을 감지할 수 없다. 스키마가 바뀌면 `rank_field_missing` 이 튄다.
        "participant_parsed_rows": parsed_rows,
        "rank_absent": parse_stats.get("rank_absent", 0),
        "rank_field_missing": field_missing,
        "rank_unparsed": parse_stats.get("rank_unparsed", 0),
        "api_items": total_items,
        "range": f"{overall_start}~{overall_end}",
        "pages_fetched": pages_fetched,
        "inserted": inserted,
        "updated": updated,
        "corrected": corrected,
        "unchanged": unchanged,
        "skipped": skipped,
        "participants_counted": counted,
        **p_summary,
    }
    logger.info(f"opening_crawler: {summary}")
    return summary
