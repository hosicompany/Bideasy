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
#: 페이지 간 간격. 같은 API 를 쓰는 `scripts/census_construction.py` 와 같은 값.
#: 표적 재조회는 회당 수천 페이지라 이게 없으면 공공 API 한도에 부딪힌다.
_PAGE_INTERVAL_SEC = 0.3

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
        # (None 이면 upsert 가 기존 값을 안 지운다 — `_upsert_opening_result`)
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
    셀 수 없고, `_upsert_opening_result` 는 낙찰가가 이미 있는 행을 건드리지
    않으므로(실 결과는 안 바뀐다는 규칙) 그 경로로도 못 채운다.

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


def windows_for_dates(dates) -> list[tuple[datetime, datetime]]:
    """날짜 목록 → API 조회 창(그날 00:00 ~ 23:59) 목록.

    개찰 API 는 **날짜 창 조회만** 지원한다(2026-08-13 실측: `bidNtceNo` 를 줘도
    무시되고 `bidNtceNo` 단독은 "필수값 입력 에러"). 그래서 특정 공고를 다시
    보려면 그 공고의 개찰일을 통째로 훑는 수밖에 없다.
    """
    now = datetime.now()
    out = []
    for d in dates:
        start = datetime.combine(d, datetime.min.time())
        # ⚠️ **미래 종료시각을 요청하면 안 된다** — API 가 "입력범위값 초과
        # 에러"를 낸다(docs/BACKFILL_VALIDATION_DESIGN.md §3 probe). 오늘 날짜가
        # 목록에 들어오면 23:59 는 미래다.
        end = min(start.replace(hour=23, minute=59), now)
        if end <= start:
            continue          # 그날이 아직 시작도 안 했다
        out.append((start, end))
    return out


def crawl_recent_openings(days_back: int = 2, max_pages: int = 200,
                          windows: list[tuple[datetime, datetime]] | None = None) -> dict:
    """최근 N일 (기본 2일) 동안 개찰된 공사 결과 일괄 크롤 → DB upsert.

    매일 Celery beat 가 호출. days_back=2 로 안전마진(하루 누락 방지).

    `windows` 를 주면 그 창만 조회한다 — 채점 대기 공고의 개찰일을 표적
    재조회하는 경로(`verification.recheck_pending_openings`)가 쓴다. 정기 크롤은
    개찰일 기준 2일 창이라, **낙찰자 확정(적격심사)이 그 안에 안 끝난 공고는
    영영 결과가 안 붙는다**(실측: 채점 도달률이 8~9일이 지나도 33.8% 정체).
    """
    if windows is None:
        end_dt = datetime.now()
        start_dt = end_dt - timedelta(days=days_back)
        windows = list(_daily_windows(start_dt, end_dt))
    if not windows:
        return {"ok": True, "note": "조회할 창이 없습니다", "pages_fetched": 0,
                "inserted": 0, "updated": 0, "skipped": 0}
    start_dt, end_dt = windows[0][0], windows[-1][1]
    overall_start = start_dt.strftime("%Y%m%d%H%M")
    overall_end = end_dt.strftime("%Y%m%d%H%M")

    logger.info(f"opening_crawler: range {overall_start} ~ {overall_end}")

    db = SessionLocal()
    inserted = 0
    updated = 0
    skipped = 0
    pages_fetched = 0
    seen: set[str] = set()  # 이번 세션 dedupe (API 가 동일 bid_no 를 여러 row 로 반환)

    # 참가자 저장 대상 = 모의투찰 등록 공고만 (설계 §P4 — 전수 저장 금지).
    # API 는 참가자별로 row 를 쪼개 주므로, 낙찰자 판별과 별개로 여기서 줍는다.
    registered_bid_nos, scope_ok = _load_registered_bid_nos(db)
    parse_stats: dict[str, int] = {}
    total_items = 0
    counted = 0
    failed_windows: list[str] = []
    participant_targets = 0
    p_totals = {"participant_bids": 0, "participant_rows_changed": 0,
                "participant_errors": 0, "participant_structural_errors": 0}

    # ⚠️ **창 하나를 끝까지 완결시킨 뒤 다음 창으로 간다.** 참가자를 전 창이
    # 끝난 뒤에 한꺼번에 저장하면 세 가지가 동시에 깨진다:
    #   ① 창 k 에서 예외가 나면 창 1..k-1 의 참가자가 통째로 사라지는데
    #      참여사수(`OpeningResult`)는 이미 커밋돼 두 저장소가 갈라진다.
    #   ② 창 수만큼 참가자 dict 가 메모리에 쌓인다(재조회는 10창 = 수십만 행,
    #      워커 상한은 512M).
    #   ③ 한 날짜의 결함이 나머지 날짜를 전부 죽인다(재조회는 오래된 순
    #      고정이라 같은 독약 날짜가 매일 큐를 막는다).
    # 창 단위로 가두면 셋 다 사라진다 — CLAUDE.md 함정 17 과 같은 원칙이다.
    for window_start, window_end in windows:
        start_str = window_start.strftime("%Y%m%d%H%M")
        end_str = window_end.strftime("%Y%m%d%H%M")
        window_inserted = 0
        window_updated = 0
        window_skipped = 0
        # 참여사수 = 이 창에서 그 공고로 온 참가자 행 수. 창 단위로 세고
        # 창 단위로 반영한다(창을 넘겨 누적하면 재크롤 겹침에서 부풀어 오른다).
        # **저장과 같은 키로** 센다. raw 행을 그냥 더하면 API 가 같은 행을 두 번
        # 준 날 `participants_count` 만 부풀어 `opening_participants` 행 수와
        # 영구히 어긋난다 — 두 저장소가 서로 다른 말을 하게 된다.
        window_keys: dict[str, set] = {}
        window_participants: dict[str, list[dict]] = {}
        logger.info(f"opening_crawler: window {start_str} ~ {end_str}")
        try:
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
                            window_participants.setdefault(p["bid_no"], []).append(p)
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
                # 공공 API 예우 — 같은 API 를 쓰는 census 스크립트와 같은 간격.
                # 재조회는 회당 수천 페이지라 이게 없으면 한도에 부딪힌다.
                time.sleep(_PAGE_INTERVAL_SEC)
            else:
                raise RuntimeError(
                    f"page limit reached with a full page: {start_str}~{end_str} "
                    f"(max_pages={max_pages})"
                )
            # 창 집계는 **전 공고**를 채운다. 등록 공고는 아래에서 실제 행 수로
            # 덮으므로 순서상 그쪽이 이긴다. 여기서 등록 공고를 미리 빼면,
            # 저장이 실패한 공고가 어느 경로에서도 안 채워져 영영 NULL 로 남는다.
            counted += _apply_participant_counts(
                db, {b: len(keys) for b, keys in window_keys.items()})
            db.commit()
        except Exception as e:  # noqa: BLE001
            db.rollback()
            failed_windows.append(f"{start_str}: {type(e).__name__}: {e}")
            logger.error(f"opening_crawler: window {start_str} 실패 — "
                         f"{type(e).__name__}: {e}")
            continue
        inserted += window_inserted
        updated += window_updated
        skipped += window_skipped

        # 이 창의 참가자를 **여기서** 저장한다. 다음 창이 실패해도 이건 남는다.
        if window_participants:
            participant_targets += len(window_participants)
            pdb = SessionLocal()
            try:
                ps = _save_participants(pdb, window_participants)
                # 등록 공고의 참여사수 = 병합 후 실제 참가자 행 수. 두 저장소가
                # 같은 소스를 보게 해야 "행 수는 5인데 화면은 12"가 안 나온다.
                applied = _apply_participant_counts(
                    pdb, ps.pop("participant_final_counts"))
                pdb.commit()
                counted += applied
                for k, v in ps.items():
                    p_totals[k] = p_totals.get(k, 0) + v
            except Exception as e:  # noqa: BLE001
                pdb.rollback()
                logger.error(f"opening_crawler: 창 {start_str} 참가자 저장 실패: "
                             f"{type(e).__name__}: {e}")
            finally:
                pdb.close()
    db.close()

    p_summary = p_totals
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
            f"(대상 {participant_targets}공고) — 반복되면 원인을 확인할 것"
        )

    # 창 하나가 실패해도 나머지는 처리한다(창 단위 격리). 다만 **전 창이 실패**
    # 하면 그건 부분 결함이 아니라 고장이므로 실패로 보고한다.
    ok = not (failed_windows and len(failed_windows) == len(windows))
    if failed_windows:
        logger.error(f"opening_crawler: 실패한 창 {len(failed_windows)}/{len(windows)} — "
                     f"{failed_windows[:3]}")

    summary = {
        "ok": ok,
        "error": failed_windows[0] if (failed_windows and not ok) else None,
        "failed_windows": failed_windows,
        "windows": len(windows),
        "participant_ok": participant_ok,
        "participant_scope_ok": scope_ok,
        "participant_targets": participant_targets,
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
        "skipped": skipped,
        "participants_counted": counted,
        **p_summary,
    }
    logger.info(f"opening_crawler: {summary}")
    return summary
