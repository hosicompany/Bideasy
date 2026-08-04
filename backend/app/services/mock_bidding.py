"""모의투찰 (Shadow Bidding) — 등록·채점 단일 진입점.

설계·게이트 정본: `docs/MOCK_BIDDING_DESIGN.md` (구현 착수 전 동결)

이 모듈이 지키는 불변식 4가지:
1. **등록은 마감 전에만** — `registered_at < deadline_at`. 위반은 등록 거부.
   이 가드가 실험 전체의 신뢰 근거다(사후 계산이면 백테스트와 다를 게 없다).
2. **등록 행은 불변** — 재채점은 `MockBidResult` 에 새 행(`scoring_rev`+1).
3. **판정 정의는 `optimizer.simulate_params` 와 동일** — 갈라지면 자가보정과
   모의투찰이 서로 다른 말을 한다.
4. **등록 대상 규칙은 고정** — §3. 조용히 바꾸면 전후 데이터가 섞인다.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import and_, case, func
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.db import models
from app.services.calculator import CalculatorService
from app.services.lower_limits import get_lower_limit_rate

logger = get_logger(__name__)

_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
_BENCHMARK_RESULTS = _DATA_DIR / "benchmark_win_reach_results.json"

# ── 등록 대상 규칙 (§3 — 고정) ────────────────────────────────
# 전략이 정의된 가격경쟁 방식만. '협상에의한계약'처럼 가격으로 겨루지 않는
# 방식과 '수의시담'은 제외한다.
ELIGIBLE_BID_METHODS = frozenset({
    "적격심사제",
    "소액수의견적",
    "제한적최저가(낙찰하한율)",
    "최저가낙찰제",
})
EXCLUDED_NOTICE_KINDS = frozenset({"취소공고"})

# 마감 T-2h 이내에 등록한다. 너무 이르면 공고 정정을 못 반영하고,
# 너무 늦으면(=마감 후) 등록 자체가 거부된다.
REGISTER_WINDOW_HOURS = 2

ARMS = ("standard", "active", "frontier_c5", "frontier_c10", "aggressive")

_KST = ZoneInfo("Asia/Seoul")


def now_kst() -> datetime:
    """KST naive 현재시각 — 이 모듈의 모든 시각 비교·기록에 이것만 쓴다.

    `Notice.end_date` 는 공고 API 의 `opengDt`(KST 표기 문자열)를 그대로 naive
    로 저장한 값이다. 그런데 운영 컨테이너 TZ 는 UTC 라 `datetime.now()` 를
    쓰면 **두 값이 9시간 어긋난다**. 실제로 배포 직후 이 버그로 등록 후보가
    0건이었고, 더 나쁘게는 '마감 2시간 전' 창이 이미 지난 시각(KST 새벽)을
    가리켜 **마감이 지난 공고를 등록**할 수 있었다 — §0.5-1 불변식 위반.

    ⚠️ `deadline_tasks` 등 다른 태스크도 같은 오차를 갖고 있으나(일 단위라
    드러나지 않았다) 그 수정은 이 모듈 밖의 별도 과제다.
    """
    return datetime.now(_KST).replace(tzinfo=None)

# 평평한(세그먼트 무관) arm 의 사정률 — 벤치마크 §0.2 와 동일 정의
STANDARD_RATE = -2.5
AGGRESSIVE_RATE = -12.0


@dataclass
class ArmPrice:
    """한 arm 의 등록가와 산출 근거."""

    arm: str
    price: int
    bid_rate: float
    adjustment: float | None
    margin: float | None
    strategy_version: str | None


# ── 전략 파라미터 로딩 ────────────────────────────────────────

_frontier_cache: dict | None = None


def _frontier_params(cap: str) -> dict | None:
    """벤치마크가 저장한 dropout 캡별 최적 파라미터셋.

    `--exp frontier` 실행 산출물(`best_params_by_cap`). 파일이 없거나 캡이
    없으면 None → 해당 arm 은 등록하지 않는다(없는 걸 있는 척하지 않는다).
    """
    global _frontier_cache
    if _frontier_cache is None:
        try:
            data = json.loads(_BENCHMARK_RESULTS.read_text(encoding="utf-8"))
            _frontier_cache = data.get("frontier", {}).get("best_params_by_cap") or {}
        except (OSError, json.JSONDecodeError) as e:
            logger.warning(f"[mock_bidding] frontier 파라미터 로드 실패: {e}")
            _frontier_cache = {}
    return _frontier_cache.get(cap)


def _active_params() -> tuple[dict | None, str | None]:
    """자가보정 active 파라미터 + 버전 ID."""
    try:
        from app.services.autocalibrate.strategy_store import get_default_store

        v = get_default_store().load_active()
        return v.params, getattr(v, "version_id", None) or getattr(v, "version", None)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[mock_bidding] active 전략 로드 실패: {e}")
        return None, None


_code_rev_cache: str | None = None


def _code_rev() -> str:
    """등록 시점 코드 리비전 — 재현성용. 실패해도 등록을 막지 않는다."""
    global _code_rev_cache
    if _code_rev_cache is None:
        try:
            _code_rev_cache = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                capture_output=True, text=True, timeout=5,
                cwd=str(Path(__file__).resolve().parent.parent.parent),
            ).stdout.strip() or "unknown"
        except Exception:  # noqa: BLE001
            _code_rev_cache = "unknown"
    return _code_rev_cache


# ── 하한율·A값 소스 판정 ──────────────────────────────────────

def resolve_lower_limit_rate(notice: models.Notice) -> tuple[float, str]:
    """낙찰하한율과 그 출처.

    공고가 명시한 값(`sucsfbidLwltRate`, 진행중 공고의 92.6%)이 금액대 테이블
    추정보다 정확하므로 우선한다. 결측 시에만 테이블 폴백.
    """
    llr = getattr(notice, "lower_limit_rate", None)
    if llr and llr > 0:
        return float(llr), "notice"
    return (
        get_lower_limit_rate(notice.contract_type or "CONSTRUCTION", notice.basic_price),
        "table",
    )


def _a_value_of(notice: models.Notice) -> tuple[int, str]:
    a = int(getattr(notice, "a_value", 0) or 0)
    return (a, "tier2" if a > 0 else "none")


# ── arm 별 가격 산출 ──────────────────────────────────────────

def compute_arm_prices(notice: models.Notice) -> list[ArmPrice]:
    """공고 하나에 대해 5 arm 의 등록가를 산출.

    파라미터를 못 구한 arm 은 **건너뛴다**(빈 값으로 등록하지 않는다).
    """
    bp = float(notice.basic_price or 0)
    if bp <= 0:
        return []

    a_value, _ = _a_value_of(notice)
    method = notice.bid_method or "DEFAULT"
    ctype = notice.contract_type or "CONSTRUCTION"
    out: list[ArmPrice] = []

    def _flat(arm: str, rate: float) -> ArmPrice:
        price = CalculatorService.calculate_safe_bid(bp, rate, a_value)
        return ArmPrice(arm, price, round(price / bp * 100, 4), None, None, None)

    out.append(_flat("standard", STANDARD_RATE))
    out.append(_flat("aggressive", AGGRESSIVE_RATE))

    active, version = _active_params()
    if active is not None:
        r = CalculatorService.recommend_bid_price(
            basic_price=bp, bid_method=method, contract_type=ctype,
            a_value=a_value, strategy_override=active,
        )
        out.append(ArmPrice("active", r["recommended_price"], r["bid_rate"],
                            r["adjustment"], r["margin"], version))

    for arm, cap in (("frontier_c5", "5"), ("frontier_c10", "10")):
        params = _frontier_params(cap)
        if params is None:
            continue
        r = CalculatorService.recommend_bid_price(
            basic_price=bp, bid_method=method, contract_type=ctype,
            a_value=a_value, strategy_override=params,
        )
        out.append(ArmPrice(arm, r["recommended_price"], r["bid_rate"],
                            r["adjustment"], r["margin"], f"frontier_cap{cap}"))

    return out


# ── 등록 ──────────────────────────────────────────────────────

def is_eligible(notice: models.Notice) -> tuple[bool, str]:
    """§3 등록 대상 규칙. (통과여부, 사유)"""
    if (notice.contract_type or "") != "CONSTRUCTION":
        return False, "not_construction"
    if not notice.basic_price or notice.basic_price <= 0:
        return False, "no_basic_price"
    if not notice.end_date:
        return False, "no_deadline"
    if (notice.notice_kind or "") in EXCLUDED_NOTICE_KINDS:
        return False, "cancelled_notice"
    if (notice.bid_method or "") not in ELIGIBLE_BID_METHODS:
        return False, "bid_method_not_eligible"
    return True, "ok"


def register_notice(db: Session, notice: models.Notice, now: datetime | None = None) -> dict:
    """공고 하나에 5 arm 을 사전 등록. 이미 등록된 arm 은 건너뛴다.

    **마감이 지났으면 등록하지 않는다** — 사후 등록은 이 실험을 무의미하게 만든다.
    """
    now = now or now_kst()
    ok, reason = is_eligible(notice)
    if not ok:
        return {"registered": 0, "skipped": reason}

    if notice.end_date <= now:
        return {"registered": 0, "skipped": "deadline_passed"}

    existing = {
        row[0] for row in
        db.query(models.MockBid.arm).filter(models.MockBid.bid_no == notice.bid_no).all()
    }
    prices = compute_arm_prices(notice)
    if not prices:
        return {"registered": 0, "skipped": "no_arm_price"}

    llr, llr_src = resolve_lower_limit_rate(notice)
    a_value, a_src = _a_value_of(notice)
    rev = _code_rev()

    n = 0
    for ap in prices:
        if ap.arm in existing:
            continue
        db.add(models.MockBid(
            bid_no=notice.bid_no,
            arm=ap.arm,
            registered_at=now,
            deadline_at=notice.end_date,
            strategy_version=ap.strategy_version,
            code_rev=rev,
            price=ap.price,
            bid_rate=ap.bid_rate,
            adjustment=ap.adjustment,
            margin=ap.margin,
            snapshot_basic_price=float(notice.basic_price),
            snapshot_a_value=a_value,
            a_value_source=a_src,
            snapshot_lower_limit_rate=llr,
            llr_source=llr_src,
            snapshot_bid_method=notice.bid_method,
            snapshot_contract_type=notice.contract_type,
            snapshot_notice_kind=notice.notice_kind,
            status="REGISTERED",
        ))
        n += 1
    return {"registered": n, "skipped": "" if n else "already_registered"}


def register_due_notices(db: Session, window_hours: int = REGISTER_WINDOW_HOURS,
                         limit: int = 2000, now: datetime | None = None) -> dict:
    """마감 임박(window_hours 이내) 미등록 공고를 일괄 등록."""
    now = now or now_kst()
    horizon = now + timedelta(hours=window_hours)

    candidates = (
        db.query(models.Notice)
        .filter(
            models.Notice.contract_type == "CONSTRUCTION",
            models.Notice.end_date > now,
            models.Notice.end_date <= horizon,
            models.Notice.basic_price > 0,
            models.Notice.bid_method.in_(tuple(ELIGIBLE_BID_METHODS)),
        )
        .limit(limit)
        .all()
    )

    result = {"candidates": len(candidates), "notices": 0, "registered": 0, "skips": {}}
    for n in candidates:
        # **공고 단위로 커밋한다.** 마지막에 한 번만 커밋하면, 커밋 시점에야
        # 드러나는 결함(예: 대형 공고의 정수 오버플로) 하나가 그 배치의
        # 정상 등록분까지 전부 롤백시킨다 — 실제로 겪었다. 그러면 마감이
        # 지나 그 회차는 영영 등록되지 않는다(사전 등록은 재시도가 안 된다).
        try:
            r = register_notice(db, n, now=now)
            db.commit()
        except Exception as e:  # noqa: BLE001
            db.rollback()
            logger.warning(f"[mock_bidding] register 실패 {n.bid_no}: {type(e).__name__}: {e}")
            result["skips"]["error"] = result["skips"].get("error", 0) + 1
            continue
        if r["registered"]:
            result["notices"] += 1
            result["registered"] += r["registered"]
        elif r.get("skipped"):
            k = r["skipped"]
            result["skips"][k] = result["skips"].get(k, 0) + 1
    logger.info(f"[mock_bidding.register] {result}")
    return result


# ── 채점 ──────────────────────────────────────────────────────

def judge(price: float, lower_limit: float, winner_price: float) -> str:
    """판정 — `optimizer.simulate_params`(optimizer.py:94-98)와 동일 정의.

    이 함수를 고칠 때는 반드시 simulate_params 도 함께 본다.
    """
    if price < lower_limit:
        return "DROPOUT"
    if price <= winner_price:
        return "WIN"
    return "LOST"


def _failure_tags(mb: models.MockBid, actual: models.OpeningResult,
                  notice: models.Notice | None, outcome: str) -> list[str]:
    """오답노트 태깅 (§6) — 태그별 실패율이 곧 제품 경고가 된다."""
    tags: list[str] = []
    if not mb.snapshot_a_value:
        tags.append("A값_결측")
    if mb.llr_source == "table":
        tags.append("하한율_테이블폴백")
    if (mb.snapshot_notice_kind or "") == "변경공고":
        tags.append("기초금액_정정")
    if notice is not None:
        if (notice.re_notice_yn or "") == "Y":
            tags.append("재공고건")
        if notice.prdprc_total is not None and (
            notice.prdprc_total != 15 or notice.prdprc_draw != 4
        ):
            tags.append("예가_비표준")
        # 등록 후 기초금액이 바뀐 건 — 스냅샷이 있어서 알 수 있다
        if notice.basic_price and mb.snapshot_basic_price and (
            abs(float(notice.basic_price) - float(mb.snapshot_basic_price)) > 1.0
        ):
            tags.append("기초금액_변경됨")
    if actual.reserved_price and mb.snapshot_basic_price:
        ratio = float(actual.reserved_price) / float(mb.snapshot_basic_price)
        if ratio < 0.97 or ratio > 1.03:
            tags.append("사정률_극단")
    return tags


def estimate_rank(our_price: int, participant_prices: list[int]) -> int:
    """우리 등록가를 참가자 투찰가 목록에 끼워넣었을 때의 개찰 순위(1 = 최저가).

    개찰 API 의 `opengRank` 와 같은 축이다 — 하한선 미달(무효) 참가자도 순위에
    포함된다. 동가는 같은 순위로 본다(우리보다 **엄격히 낮은** 가격 수 + 1).

    ⚠️ 판정(judge)의 대체가 아니라 별개 지표다(§0.2 3차). WIN/LOST/DROPOUT
    정의는 simulate_params 와 동일하게 유지된다(§P3) — 등수가 1이어도 하한선
    미달이면 DROPOUT 이고, 그 모순처럼 보이는 조합이 바로 배울 거리다.
    """
    return 1 + sum(1 for p in participant_prices if p < our_price)


def _participants_by_bid(db: Session, bid_nos: list[str]) -> dict[str, list[models.OpeningParticipant]]:
    """참가자 행을 공고별로 묶어 반환 (등록 공고만 저장돼 있다 — §P4)."""
    out: dict[str, list[models.OpeningParticipant]] = {}
    if not bid_nos:
        return out
    rows = (
        db.query(models.OpeningParticipant)
        .filter(models.OpeningParticipant.bid_no.in_(bid_nos))
        .all()
    )
    for p in rows:
        out.setdefault(p.bid_no, []).append(p)
    return out


def score_mock_bid(db: Session, mb: models.MockBid,
                   actual: models.OpeningResult | None,
                   notice: models.Notice | None = None,
                   participants: list[models.OpeningParticipant] | None = None,
                   ) -> models.MockBidResult | None:
    """등록 1건을 채점해 결과 행을 만든다(등록 행은 건드리지 않는다).

    이미 같은 내용으로 채점된 적이 있으면 None (중복 채점 방지).
    참가자 데이터가 있으면 첫 채점에서 등수까지 채운다 — 참가자 크롤(19:00)이
    채점(20:30)보다 앞서므로 대부분 여기서 채워지고, 늦게 도착한 건은
    `backfill_participant_ranks` 가 새 scoring_rev 로 채운다.
    """
    prev = (
        db.query(models.MockBidResult)
        .filter(models.MockBidResult.mock_bid_id == mb.id)
        .order_by(models.MockBidResult.scoring_rev.desc())
        .first()
    )

    if actual is None or not actual.winner_price:
        if prev is not None:
            return None  # 이미 NO_RESULT 로 기록됨 — 매번 새 행을 쌓지 않는다
        res = models.MockBidResult(
            mock_bid_id=mb.id, scoring_rev=1, outcome="NO_RESULT",
            scored_at=now_kst(),
        )
        db.add(res)
        return res

    if prev is not None and prev.outcome not in ("NO_RESULT",):
        return None  # 확정 채점이 이미 있음

    winner = float(actual.winner_price)
    llr = float(mb.snapshot_lower_limit_rate or 0)
    reserved = float(actual.reserved_price or 0)

    # 하한선 = 예정가격 × 하한율. 예정가격이 없으면 기초금액으로 근사(정직하게 태깅).
    base_for_limit = reserved if reserved > 0 else float(mb.snapshot_basic_price or 0)
    a = float(mb.snapshot_a_value or 0)
    if a > 0:
        lower_limit = (base_for_limit - a) * llr / 100.0 + a
    else:
        lower_limit = base_for_limit * llr / 100.0

    outcome = judge(float(mb.price), lower_limit, winner)

    ratio_actual = (reserved / float(mb.snapshot_basic_price)
                    if reserved > 0 and mb.snapshot_basic_price else None)
    ratio_pred = (1.0 + (mb.adjustment or 0) / 100.0) if mb.adjustment is not None else None

    tags = _failure_tags(mb, actual, notice, outcome)
    if reserved <= 0:
        tags.append("예정가격_결측")

    # 등수 재구성 (§4-3) — 참가자 투찰가 목록에 우리 등록가를 끼워넣는다.
    p_prices = [int(p.bid_price) for p in (participants or []) if p.bid_price]
    est_rank = estimate_rank(int(mb.price), p_prices) if p_prices else None
    participants_count = len(p_prices) if p_prices else actual.participants_count

    res = models.MockBidResult(
        mock_bid_id=mb.id,
        scoring_rev=(prev.scoring_rev + 1) if prev else 1,
        outcome=outcome,
        actual_reserved_price=reserved or None,
        actual_winner_price=winner,
        actual_lower_limit=round(lower_limit, 2),
        estimated_rank=est_rank,
        participants_count=participants_count,
        gap_to_winner_pct=round((float(mb.price) - winner) / winner * 100, 4) if winner else None,
        gap_to_limit_pct=(round((float(mb.price) - lower_limit) / lower_limit * 100, 4)
                          if lower_limit else None),
        reserved_ratio_actual=round(ratio_actual, 6) if ratio_actual else None,
        reserved_ratio_predicted=round(ratio_pred, 6) if ratio_pred else None,
        ratio_error=(round(abs(ratio_actual - ratio_pred), 6)
                     if ratio_actual and ratio_pred else None),
        failure_tags=tags or None,
        scored_at=now_kst(),
    )
    db.add(res)
    mb.status = "SCORED"   # 상태 플래그만 갱신 — 등록 내용(가격·스냅샷)은 불변
    return res


def score_pending(db: Session, limit: int = 5000) -> dict:
    """마감이 지난 미채점 등록분을 일괄 채점.

    ⚠️ 잔량은 계속 쌓인다. 낙찰자 확정에 며칠 걸리는 동안 `NO_RESULT` 로 남은
    등록분이 매일 다시 대상이 되고, 하루 등록이 1,400건 규모라 **나흘이면
    limit 에 닿는다**. 그래서 두 가지를 지킨다:

    1. **마감이 오래된 것부터** 채점한다. 정렬이 없으면 DB 가 주는 임의 순서라,
       잘려 나간 쪽이 매일 같은 자리에 남아 영영 채점되지 않을 수 있다.
    2. 잘린 잔량을 **로그와 반환값에 남긴다**. `scored: 5000` 만 보면 정상처럼
       보이는데 실제로는 데이터가 새고 있는 상황이 조용히 지나간다.
    """
    now = now_kst()
    base = db.query(models.MockBid).filter(
        models.MockBid.status == "REGISTERED",
        models.MockBid.deadline_at < now,
    )
    total_due = base.count()
    pending = (
        base.order_by(models.MockBid.deadline_at.asc(), models.MockBid.id.asc())
        .limit(limit)
        .all()
    )
    if not pending:
        return {"pending": 0, "scored": 0, "outcomes": {}, "deferred": 0}

    deferred = max(0, total_due - len(pending))
    if deferred:
        logger.warning(
            f"[mock_bidding.score] 채점 대상 {total_due}건 중 {len(pending)}건만 처리 "
            f"— {deferred}건이 이번 회차에서 밀렸다(limit={limit}). "
            f"마감 오래된 순으로 처리하므로 다음 회차에 이어서 잡힌다."
        )

    bid_nos = list({mb.bid_no for mb in pending})
    actuals = {
        r.bid_no: r for r in
        db.query(models.OpeningResult)
        .filter(models.OpeningResult.bid_no.in_(bid_nos)).all()
    }
    notices = {
        n.bid_no: n for n in
        db.query(models.Notice).filter(models.Notice.bid_no.in_(bid_nos)).all()
    }
    participants = _participants_by_bid(db, bid_nos)

    outcomes: dict[str, int] = {}
    scored = 0
    for mb in pending:
        try:
            res = score_mock_bid(db, mb, actuals.get(mb.bid_no), notices.get(mb.bid_no),
                                 participants=participants.get(mb.bid_no))
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[mock_bidding] score 실패 id={mb.id}: {type(e).__name__}: {e}")
            continue
        if res is None:
            continue
        scored += 1
        outcomes[res.outcome] = outcomes.get(res.outcome, 0) + 1
    db.commit()

    result = {"pending": len(pending), "scored": scored, "outcomes": outcomes,
              "deferred": deferred}
    logger.info(f"[mock_bidding.score] {result}")
    return result


def backfill_participant_ranks(db: Session, limit: int = 5000) -> dict:
    """참가자 데이터가 뒤늦게 도착한 채점분의 등수를 채운다 — **새 scoring_rev 행으로**.

    채점 시점에 참가자가 이미 있으면 `score_mock_bid` 가 등수까지 채우지만,
    참가자 크롤이 늦거나(적격검사 지연·재크롤) Phase 2 배포 전 채점분은 비어
    있다. §0.5-3 이 기존 결과 행 UPDATE 를 금지하므로, 이전 판정을 그대로
    복사하고 등수만 더한 새 행(scoring_rev+1)을 쌓는다 — 집계는 최신 rev 만 본다.
    """
    sq = _latest_rev_sq(db)
    rows = (
        db.query(models.MockBidResult, models.MockBid)
        .join(sq, and_(models.MockBidResult.mock_bid_id == sq.c.mock_bid_id,
                       models.MockBidResult.scoring_rev == sq.c.max_rev))
        .join(models.MockBid, models.MockBid.id == models.MockBidResult.mock_bid_id)
        .filter(models.MockBidResult.outcome.in_(("WIN", "LOST", "DROPOUT")),
                models.MockBidResult.estimated_rank.is_(None))
        # score_pending 과 같은 이유로 순서를 고정한다 — 정렬 없이 자르면
        # 잘려 나간 쪽이 매일 같은 자리에 남아 등수가 영영 안 채워질 수 있다.
        .order_by(models.MockBidResult.mock_bid_id.asc())
        .limit(limit)
        .all()
    )
    if not rows:
        return {"candidates": 0, "backfilled": 0}

    participants = _participants_by_bid(db, list({b.bid_no for _, b in rows}))
    backfilled = 0
    for prev, mb in rows:
        p_prices = [int(p.bid_price) for p in participants.get(mb.bid_no, []) if p.bid_price]
        if not p_prices:
            continue  # 참가자가 아직 없으면 다음 실행에서 다시 본다
        try:
            db.add(models.MockBidResult(
                mock_bid_id=mb.id,
                scoring_rev=prev.scoring_rev + 1,
                outcome=prev.outcome,
                actual_reserved_price=prev.actual_reserved_price,
                actual_winner_price=prev.actual_winner_price,
                actual_lower_limit=prev.actual_lower_limit,
                estimated_rank=estimate_rank(int(mb.price), p_prices),
                participants_count=len(p_prices),
                gap_to_winner_pct=prev.gap_to_winner_pct,
                gap_to_limit_pct=prev.gap_to_limit_pct,
                reserved_ratio_actual=prev.reserved_ratio_actual,
                reserved_ratio_predicted=prev.reserved_ratio_predicted,
                ratio_error=prev.ratio_error,
                failure_tags=prev.failure_tags,
                scored_at=now_kst(),
            ))
            # 건 단위 커밋 — 1건 결함이 배치 전체를 롤백시키지 않게(등록 배치에서 실제로 겪은 사고)
            db.commit()
            backfilled += 1
        except Exception as e:  # noqa: BLE001
            db.rollback()
            logger.warning(f"[mock_bidding] rank backfill 실패 id={mb.id}: {type(e).__name__}: {e}")

    result = {"candidates": len(rows), "backfilled": backfilled}
    logger.info(f"[mock_bidding.rank_backfill] {result}")
    return result


# ── 집계 (어드민·리포트) ──────────────────────────────────────
# 재채점(NO_RESULT→확정, 등수 백필)은 새 scoring_rev 행을 쌓으므로, 집계는
# 반드시 **등록 건당 최신 rev 하나만** 봐야 한다 — 전 행을 세면 rev 가 쌓일
# 때마다 같은 등록 건이 중복 집계된다.

def _latest_rev_sq(db: Session):
    """등록 건별 최신 scoring_rev 서브쿼리 — 모든 집계의 공통 진입."""
    return (
        db.query(models.MockBidResult.mock_bid_id.label("mock_bid_id"),
                 func.max(models.MockBidResult.scoring_rev).label("max_rev"))
        .group_by(models.MockBidResult.mock_bid_id)
        .subquery()
    )


def summarize(db: Session, bid_method: str | None = None) -> dict:
    """arm 별 성적표. 1차 지표는 무효율(dropout) — 낙찰률이 아니다(§0.2)."""
    sq = _latest_rev_sq(db)
    q = (
        db.query(models.MockBid.arm, models.MockBidResult.outcome,
                 models.MockBidResult.ratio_error)
        .join(models.MockBidResult, models.MockBidResult.mock_bid_id == models.MockBid.id)
        .join(sq, and_(models.MockBidResult.mock_bid_id == sq.c.mock_bid_id,
                       models.MockBidResult.scoring_rev == sq.c.max_rev))
    )
    if bid_method:
        q = q.filter(models.MockBid.snapshot_bid_method == bid_method)

    per: dict[str, dict] = {}
    for arm, outcome, ratio_err in q.all():
        d = per.setdefault(arm, {"WIN": 0, "LOST": 0, "DROPOUT": 0,
                                 "NO_RESULT": 0, "VOID": 0, "_err": []})
        d[outcome] = d.get(outcome, 0) + 1
        if ratio_err is not None:
            d["_err"].append(ratio_err)

    out = {}
    for arm, d in per.items():
        judged = d["WIN"] + d["LOST"] + d["DROPOUT"]
        errs = d.pop("_err")
        out[arm] = {
            "judged": judged,
            "no_result": d["NO_RESULT"],
            "win": d["WIN"],
            "lost": d["LOST"],
            "dropout": d["DROPOUT"],
            # 1차 지표
            "dropout_rate": round(d["DROPOUT"] / judged * 100, 3) if judged else None,
            "win_rate": round(d["WIN"] / judged * 100, 3) if judged else None,
            "mean_ratio_error": round(sum(errs) / len(errs), 6) if errs else None,
        }
    return out


def scoring_reach(db: Session) -> dict:
    """G-A(파이프라인 건전성) — 등록분의 채점 도달률."""
    total = db.query(models.MockBid).count()
    scored = (
        db.query(models.MockBidResult.mock_bid_id)
        .filter(models.MockBidResult.outcome.notin_(("NO_RESULT",)))
        .distinct().count()
    )
    return {
        "registered": total,
        "scored": scored,
        "reach_pct": round(scored / total * 100, 2) if total else None,
        "gate_g_a_threshold": 60.0,
    }


def failure_tag_stats(db: Session) -> dict:
    """오답노트 — 태그별 등장·무효 건수. 여기서 나온 사실이 제품 경고가 된다."""
    sq = _latest_rev_sq(db)
    rows = (
        db.query(models.MockBidResult.failure_tags, models.MockBidResult.outcome)
        .join(sq, and_(models.MockBidResult.mock_bid_id == sq.c.mock_bid_id,
                       models.MockBidResult.scoring_rev == sq.c.max_rev))
        .filter(models.MockBidResult.failure_tags.isnot(None)).all()
    )
    stats: dict[str, dict] = {}
    for tags, outcome in rows:
        for t in (tags or []):
            s = stats.setdefault(t, {"total": 0, "dropout": 0, "win": 0})
            s["total"] += 1
            if outcome == "DROPOUT":
                s["dropout"] += 1
            elif outcome == "WIN":
                s["win"] += 1
    for s in stats.values():
        s["dropout_rate"] = round(s["dropout"] / s["total"] * 100, 2) if s["total"] else None
    return dict(sorted(stats.items(), key=lambda kv: -kv[1]["total"]))


# ── 시각화 집계 (어드민 차트 전용) ────────────────────────────
# 지표 우선순위(§0.2)는 화면(admin.js pages.mockbidding)이 지킨다 —
# 여기는 데이터만 만든다. 전부 최신 rev 기준.

_JUDGED = ("WIN", "LOST", "DROPOUT")

# 등수 히스토그램 상한 — 이 위는 "11+" 로 묶는다(꼬리가 길면 분포가 안 보인다)
RANK_HISTOGRAM_CAP = 10

# 낙찰가 대비 격차(%) 버킷 경계 — 음수 = 낙찰가 이하(WIN/무효권), 양수 = 초과(LOST).
# "0~0.5%" 구간이 '아깝게 놓친' 건이다.
GAP_BUCKETS = ("≤-5", "-5~-2", "-2~-0.5", "-0.5~0", "0~0.5", "0.5~1", "1~2", "2~5", ">5")


def rank_distribution(db: Session) -> dict:
    """arm 별 추정 등수 분포 (§0.2 3차 지표) — 우리가 몇 등에 몰리는지.

    등수는 Phase 2 참가자 데이터가 붙은 건에만 있다(없으면 빈 dict).
    """
    sq = _latest_rev_sq(db)
    rows = (
        db.query(models.MockBid.arm, models.MockBidResult.estimated_rank,
                 func.count().label("n"))
        .join(models.MockBidResult, models.MockBidResult.mock_bid_id == models.MockBid.id)
        .join(sq, and_(models.MockBidResult.mock_bid_id == sq.c.mock_bid_id,
                       models.MockBidResult.scoring_rev == sq.c.max_rev))
        .filter(models.MockBidResult.estimated_rank.isnot(None),
                models.MockBidResult.outcome.in_(_JUDGED))
        .group_by(models.MockBid.arm, models.MockBidResult.estimated_rank)
        .all()
    )
    out: dict[str, dict[str, int]] = {}
    for arm, rank, n in rows:
        label = str(rank) if rank <= RANK_HISTOGRAM_CAP else f"{RANK_HISTOGRAM_CAP + 1}+"
        d = out.setdefault(arm, {})
        d[label] = d.get(label, 0) + n
    return out


def gap_distribution(db: Session) -> dict:
    """arm 별 낙찰가 대비 격차 분포 — "얼마나 아깝게 놓쳤나"를 버킷으로.

    gap_to_winner_pct = (우리가격 − 낙찰가)/낙찰가 × 100. 버킷 경계는
    GAP_BUCKETS — SQL CASE 로 묶는다(행 단위로 끌어오면 표본이 쌓일수록 무겁다).
    """
    g = models.MockBidResult.gap_to_winner_pct
    bucket = case(
        (g <= -5, GAP_BUCKETS[0]),
        (g <= -2, GAP_BUCKETS[1]),
        (g <= -0.5, GAP_BUCKETS[2]),
        (g <= 0, GAP_BUCKETS[3]),
        (g <= 0.5, GAP_BUCKETS[4]),
        (g <= 1, GAP_BUCKETS[5]),
        (g <= 2, GAP_BUCKETS[6]),
        (g <= 5, GAP_BUCKETS[7]),
        else_=GAP_BUCKETS[8],
    )
    sq = _latest_rev_sq(db)
    rows = (
        db.query(models.MockBid.arm, bucket.label("bucket"), func.count().label("n"))
        .join(models.MockBidResult, models.MockBidResult.mock_bid_id == models.MockBid.id)
        .join(sq, and_(models.MockBidResult.mock_bid_id == sq.c.mock_bid_id,
                       models.MockBidResult.scoring_rev == sq.c.max_rev))
        .filter(g.isnot(None), models.MockBidResult.outcome.in_(_JUDGED))
        .group_by(models.MockBid.arm, bucket)
        .all()
    )
    out: dict[str, dict[str, int]] = {}
    for arm, b, n in rows:
        out.setdefault(arm, {})[b] = n
    return out


def ratio_error_trend(db: Session, arm: str = "active") -> list[dict]:
    """사정률 예측 오차(§0.2 4차)의 일별 평균 추이.

    arm 하나로 고정하는 이유: 예측(adjustment)이 arm 마다 달라 섞으면 신호가
    오염된다. 기본은 운영 정본인 active. (standard/aggressive 는 adjustment 를
    기록하지 않아 오차 자체가 없다.)
    """
    sq = _latest_rev_sq(db)
    day = func.date(models.MockBidResult.scored_at)
    rows = (
        db.query(day.label("d"),
                 func.avg(models.MockBidResult.ratio_error).label("e"),
                 func.count().label("n"))
        .join(models.MockBid, models.MockBid.id == models.MockBidResult.mock_bid_id)
        .join(sq, and_(models.MockBidResult.mock_bid_id == sq.c.mock_bid_id,
                       models.MockBidResult.scoring_rev == sq.c.max_rev))
        .filter(models.MockBid.arm == arm,
                models.MockBidResult.ratio_error.isnot(None))
        .group_by(day)
        .order_by(day)
        .all()
    )
    return [{"date": str(d), "mean_error": round(float(e), 6), "n": n} for d, e, n in rows]


def segment_stats(db: Session, arm: str = "active") -> list[dict]:
    """세그먼트(입찰방법 × 금액대) 교차표 — arm 하나 기준(기본 active).

    금액대 경계는 autocalibrate `dataset.get_bracket` 과 동일해야 한다
    (calculator._get_price_bracket) — 어휘가 갈라지면 자가보정 세그먼트와
    비교할 수 없다.
    """
    bp = models.MockBid.snapshot_basic_price
    bracket = case(
        (bp < 1e8, "small"),
        (bp < 5e8, "medium"),
        (bp < 1e9, "large"),
        (bp < 5e9, "xlarge"),
        else_="xxlarge",
    )
    sq = _latest_rev_sq(db)
    rows = (
        db.query(models.MockBid.snapshot_bid_method, bracket.label("bracket"),
                 models.MockBidResult.outcome, func.count().label("n"))
        .join(models.MockBidResult, models.MockBidResult.mock_bid_id == models.MockBid.id)
        .join(sq, and_(models.MockBidResult.mock_bid_id == sq.c.mock_bid_id,
                       models.MockBidResult.scoring_rev == sq.c.max_rev))
        .filter(models.MockBid.arm == arm,
                models.MockBidResult.outcome.in_(_JUDGED))
        .group_by(models.MockBid.snapshot_bid_method, bracket,
                  models.MockBidResult.outcome)
        .all()
    )
    cells: dict[tuple, dict[str, int]] = {}
    for method, brk, outcome, n in rows:
        c = cells.setdefault((method or "?", brk), {"WIN": 0, "LOST": 0, "DROPOUT": 0})
        c[outcome] = c.get(outcome, 0) + n
    out = []
    for (method, brk), c in sorted(cells.items()):
        judged = c["WIN"] + c["LOST"] + c["DROPOUT"]
        out.append({
            "bid_method": method,
            "bracket": brk,
            "judged": judged,
            "win": c["WIN"],
            "lost": c["LOST"],
            "dropout": c["DROPOUT"],
            "dropout_rate": round(c["DROPOUT"] / judged * 100, 2) if judged else None,
            "win_rate": round(c["WIN"] / judged * 100, 2) if judged else None,
        })
    return out
