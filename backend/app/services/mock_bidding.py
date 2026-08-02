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
        try:
            r = register_notice(db, n, now=now)
        except Exception as e:  # noqa: BLE001
            # 공고 1건의 결함이 배치 전체를 끊지 않게 가둔다.
            logger.warning(f"[mock_bidding] register 실패 {n.bid_no}: {type(e).__name__}: {e}")
            result["skips"]["error"] = result["skips"].get("error", 0) + 1
            continue
        if r["registered"]:
            result["notices"] += 1
            result["registered"] += r["registered"]
        elif r.get("skipped"):
            k = r["skipped"]
            result["skips"][k] = result["skips"].get(k, 0) + 1
    db.commit()
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


def score_mock_bid(db: Session, mb: models.MockBid,
                   actual: models.OpeningResult | None,
                   notice: models.Notice | None = None) -> models.MockBidResult | None:
    """등록 1건을 채점해 결과 행을 만든다(등록 행은 건드리지 않는다).

    이미 같은 내용으로 채점된 적이 있으면 None (중복 채점 방지).
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

    res = models.MockBidResult(
        mock_bid_id=mb.id,
        scoring_rev=(prev.scoring_rev + 1) if prev else 1,
        outcome=outcome,
        actual_reserved_price=reserved or None,
        actual_winner_price=winner,
        actual_lower_limit=round(lower_limit, 2),
        participants_count=actual.participants_count,
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
    """마감이 지난 미채점 등록분을 일괄 채점."""
    now = now_kst()
    pending = (
        db.query(models.MockBid)
        .filter(models.MockBid.status == "REGISTERED",
                models.MockBid.deadline_at < now)
        .limit(limit)
        .all()
    )
    if not pending:
        return {"pending": 0, "scored": 0, "outcomes": {}}

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

    outcomes: dict[str, int] = {}
    scored = 0
    for mb in pending:
        try:
            res = score_mock_bid(db, mb, actuals.get(mb.bid_no), notices.get(mb.bid_no))
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[mock_bidding] score 실패 id={mb.id}: {type(e).__name__}: {e}")
            continue
        if res is None:
            continue
        scored += 1
        outcomes[res.outcome] = outcomes.get(res.outcome, 0) + 1
    db.commit()

    result = {"pending": len(pending), "scored": scored, "outcomes": outcomes}
    logger.info(f"[mock_bidding.score] {result}")
    return result


# ── 집계 (어드민·리포트) ──────────────────────────────────────

def summarize(db: Session, bid_method: str | None = None) -> dict:
    """arm 별 성적표. 1차 지표는 무효율(dropout) — 낙찰률이 아니다(§0.2)."""
    q = (
        db.query(models.MockBid.arm, models.MockBidResult.outcome,
                 models.MockBidResult.ratio_error)
        .join(models.MockBidResult, models.MockBidResult.mock_bid_id == models.MockBid.id)
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
    rows = (
        db.query(models.MockBidResult.failure_tags, models.MockBidResult.outcome)
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
