"""
데이터 적재·정제 모듈
======================
과거 개찰 결과(opening_results_*.json)를 로드·정제해서
백테스트 / 최적화 / 가드가 공유하는 단일 데이터 소스를 제공한다.

기존에 optimize_weighted.py:load_all(), mock_bidding_test.py:load_exam_data()
등 3곳에 중복되어 있던 로딩 로직을 통합.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from app.services.bid_data_quality import classify_base_consistency

# backend/app/services/autocalibrate/dataset.py → backend/data
_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent.parent
_DATA_DIR = _BACKEND_DIR / "data"

# 금액대 5단계 (calculator._get_price_bracket 과 동일 경계)
BRACKETS = ["small", "medium", "large", "xlarge", "xxlarge"]
# 전략이 정의된 입찰방법 (DEFAULT 는 폴백)
KNOWN_METHODS = ["적격심사제", "소액수의견적"]


def get_bracket(basic_price: float) -> str:
    """기초금액 → 금액대 (calculator._get_price_bracket 과 동일)."""
    if basic_price < 1e8:
        return "small"
    elif basic_price < 5e8:
        return "medium"
    elif basic_price < 1e9:
        return "large"
    elif basic_price < 5e9:
        return "xlarge"
    else:
        return "xxlarge"


@dataclass
class BidRecord:
    """개찰 결과 한 건 (정제·검증 완료). 원본 + 파생 필드."""

    bid_no: str
    title: str
    org: str
    bid_method: str
    basic_price: float
    estimated_price: float
    reserved_price: float       # 실제 예정가격 (정답)
    winner_price: float          # 실제 낙찰가 (정답)
    winner_rate: float           # 실제 낙찰률 (정답)
    lower_limit_rate: float
    year: int
    # 공고의 A값. 과거 정적 원장에는 없으므로 0이며, DB에 명시된 값만 쓴다.
    a_value: float = 0.0
    # confirmed | not_applicable | unknown. 0만으로는 미적용과 결측을 구분 못 한다.
    a_value_status: str = "unknown"
    bracket: str = ""
    # fingerprint 가 값뿐 아니라 어느 원장에서 어떤 정정본을 읽었는지에도
    # 민감하도록 보존한다. 모델 피처로는 사용하지 않는다.
    source: str = "unknown"
    source_revision: str = ""
    # 결과 값이 우리 시스템에 실제로 관측된 시각. 개찰일(open_date)은 결과를
    # 알게 된 시각이 아니므로 대신 쓰지 않는다. 중앙 학습 후보는 이 값이
    # 명시된 행만 허용하며, 진단용 호출부는 기본값 None을 유지할 수 있다.
    outcome_observed_at: datetime | None = None
    # opening_result_revision | opening_result_crawler |
    # static:crawled_at | static:updated_at | unknown
    outcome_observation_source: str = "unknown"
    # Latest time at which every production feature used by this historical
    # decision was actually available, and the corresponding pre-deadline
    # information boundary. These are lineage only, never model features.
    feature_observed_at: datetime | None = None
    feature_cutoff_at: datetime | None = None
    feature_observation_source: str = "unknown"

    def __post_init__(self):
        self.outcome_observed_at = _parse_observed_at(self.outcome_observed_at)
        self.feature_observed_at = _parse_observed_at(self.feature_observed_at)
        self.feature_cutoff_at = _parse_observed_at(self.feature_cutoff_at)
        if self.outcome_observed_at is None:
            self.outcome_observation_source = "unknown"
        if self.a_value < 0 or (
            self.a_value > 0
            and (
                self.a_value >= self.basic_price
                or self.a_value >= self.reserved_price
            )
        ):
            raise ValueError(
                "A값은 0 이상이며 기초금액과 실제 예정가격보다 작아야 합니다"
            )
        if not self.bracket:
            self.bracket = get_bracket(self.basic_price)

    @property
    def reserved_ratio(self) -> float:
        """사정비율 r = 예정가격 / 기초금액 — 위험 모델의 핵심 변수."""
        return self.reserved_price / self.basic_price if self.basic_price > 0 else 0.0

    @property
    def segment(self) -> tuple[str, str]:
        return (self.bid_method, self.bracket)


@dataclass
class DatasetQualityStats:
    """학습 데이터 포함/제외 통계.

    mock/benchmark와 같은 기초금액 일관성 계약을 적용했음을 후보 메타데이터에
    남기기 위한 값이다. 원장 행은 삭제하거나 수정하지 않는다.
    """

    total_seen: int = 0
    included: int = 0
    excluded_invalid_price: int = 0
    excluded_base_mismatch: int = 0
    excluded_base_unknown: int = 0
    excluded_duplicate: int = 0
    excluded_a_value_unknown: int = 0
    excluded_observation_time_unknown: int = 0
    excluded_feature_lineage_unknown: int = 0
    excluded_feature_observed_after_cutoff: int = 0
    by_source: dict[str, dict[str, int]] = field(default_factory=dict)

    def _bump(self, source: str, key: str) -> None:
        source_stats = self.by_source.setdefault(
            source,
            {
                "total_seen": 0,
                "included": 0,
                "excluded_invalid_price": 0,
                "excluded_base_mismatch": 0,
                "excluded_base_unknown": 0,
                "excluded_duplicate": 0,
                "excluded_a_value_unknown": 0,
                "excluded_observation_time_unknown": 0,
                "excluded_feature_lineage_unknown": 0,
                "excluded_feature_observed_after_cutoff": 0,
            },
        )
        setattr(self, key, getattr(self, key) + 1)
        source_stats[key] += 1

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class TemporalSplit:
    """후보 생성과 판정을 분리한 시간순 데이터셋."""

    train: list[BidRecord]
    validation: list[BidRecord]
    sealed_holdout: list[BidRecord]
    excluded_out_of_window: list[BidRecord]
    excluded_observation_unknown: list[BidRecord] = field(default_factory=list)
    excluded_observed_after_cutoff: list[BidRecord] = field(default_factory=list)
    excluded_sealed_before_selection: list[BidRecord] = field(default_factory=list)
    training_cutoff_at: datetime | None = None
    candidate_selected_at: datetime | None = None

    @property
    def counts(self) -> dict[str, int]:
        return {
            "train": len(self.train),
            "validation": len(self.validation),
            "sealed_holdout": len(self.sealed_holdout),
            "excluded_out_of_window": len(self.excluded_out_of_window),
            "excluded_observation_unknown": len(self.excluded_observation_unknown),
            "excluded_observed_after_cutoff": len(
                self.excluded_observed_after_cutoff
            ),
            "excluded_sealed_before_selection": len(
                self.excluded_sealed_before_selection
            ),
        }


def _revision_text(value) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value or "")


def _parse_observed_at(value) -> datetime | None:
    """명시된 관측시각을 비교 가능한 UTC datetime으로 정규화한다.

    DB의 기존 DateTime 컬럼은 UTC이지만 timezone 정보가 없는 값을 반환할 수
    있다. 그 경우에만 UTC로 해석한다. 파싱할 수 없는 문자열과 날짜 대용
    필드는 관측 증거로 승격하지 않는다.
    """
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _static_observation(item: dict) -> tuple[datetime | None, str]:
    """정적 원장에서 명시적 수집/정정 시각만 관측 증거로 채택한다."""
    for key in ("outcome_observed_at", "crawled_at", "updated_at"):
        observed_at = _parse_observed_at(item.get(key))
        if observed_at is not None:
            return observed_at, f"static:{key}"
    return None, "unknown"


def _quality_allows(
    basic_price: float | int | None,
    winner_price: float | int | None,
    reserved_price: float | int | None,
    *,
    source: str,
    stats: DatasetQualityStats,
    enforce_base_consistency: bool,
) -> bool:
    stats._bump(source, "total_seen")
    if not basic_price or not winner_price or not reserved_price:
        stats._bump(source, "excluded_invalid_price")
        return False
    try:
        basic = float(basic_price)
        winner = float(winner_price)
        reserved = float(reserved_price)
    except (TypeError, ValueError):
        stats._bump(source, "excluded_invalid_price")
        return False
    if (
        not all(math.isfinite(value) for value in (basic, winner, reserved))
        or basic <= 0
        or winner <= 0
        or reserved <= 0
    ):
        stats._bump(source, "excluded_invalid_price")
        return False
    if enforce_base_consistency:
        consistency = classify_base_consistency(basic, reserved)
        if consistency == "mismatch":
            stats._bump(source, "excluded_base_mismatch")
            return False
        if consistency == "unknown":
            stats._bump(source, "excluded_base_unknown")
            return False
    return True


def _load_db_records(
    db,
    existing_bid_nos: set,
    *,
    year_range: tuple[int, int] = (2021, 2027),
    strict: bool = False,
    quality_stats: DatasetQualityStats | None = None,
    enforce_base_consistency: bool = False,
    require_a_value_status: bool = False,
    require_observation_time: bool = False,
    require_feature_lineage: bool = False,
) -> list[BidRecord]:
    """누적 opening_results 테이블(매일 크롤 적재)에서 BidRecord 생성.

    정적 파일과 중복(bid_no)은 제외. estimated_price 는 reserved_price 로 대체.

    하한율은 **공고가 명시한 값(`OpeningResult.lower_limit_rate`)을 먼저** 쓰고,
    없을 때만 `lower_limits` 단일 소스에서 금액대·공고일로 조회한다. 예전에는
    87.745 를 상수로 박아 두었는데, 2026-01-30 요율 개정(10억 미만 공사
    89.745% 등) 이후로는 그 값이 실제 하한선과 달라 판정이 통째로 어긋난다.
    """
    out: list[BidRecord] = []
    stats = quality_stats or DatasetQualityStats()
    source = "opening_results_db"
    try:
        from app.db import models
        # 제외 통계를 숨기지 않기 위해 SQL에서 먼저 잘라내지 않는다.
        rows = db.query(models.OpeningResult).all()
        bid_nos = [row.bid_no for row in rows if row.bid_no]
        notices = (
            db.query(models.Notice)
            .filter(models.Notice.bid_no.in_(bid_nos))
            .all()
            if bid_nos
            else []
        )
        notice_by_bid_no = {notice.bid_no: notice for notice in notices}
        revisions = (
            db.query(models.OpeningResultRevision)
            .filter(models.OpeningResultRevision.bid_no.in_(bid_nos))
            .order_by(
                models.OpeningResultRevision.bid_no,
                models.OpeningResultRevision.revision_no,
            )
            .all()
            if bid_nos
            else []
        )
        # 같은 bid_no의 마지막 append-only revision이 현재 projection의
        # 권위 있는 관측시각이다. 정정이 생기면 과거 open_date가 아니라 이
        # 시각이 시간 누수 경계를 결정한다.
        latest_revision_by_bid_no = {
            revision.bid_no: revision for revision in revisions
        }
    except Exception:
        if strict:
            raise
        return out
    from app.services.lower_limits import get_lower_limit_rate

    for r in rows:
        open_dt = getattr(r, "open_date", None)
        year = open_dt.year if open_dt else 0
        if not year_range[0] <= year < year_range[1]:
            continue
        notice = notice_by_bid_no.get(r.bid_no)
        feature_observed_at = None
        feature_cutoff_at = None
        feature_observation_source = "unknown"
        basic_price = r.basic_price
        bid_method = r.bid_method or ""
        if require_feature_lineage:
            # OpeningResult basic/method/lower fields are post-opening truth.
            # Reconstruct only from the Notice fields the product could have
            # consumed before the deadline; otherwise coverage is fictional.
            basis_amount = float(getattr(notice, "basis_amount", 0) or 0)
            basis_at = _parse_observed_at(getattr(notice, "basis_amount_at", None))
            notice_at = _parse_observed_at(getattr(notice, "start_date", None))
            feature_cutoff_at = _parse_observed_at(
                getattr(notice, "end_date", None) or open_dt
            )
            notice_method = str(getattr(notice, "bid_method", "") or "").strip()
            a_source_for_lineage = str(
                getattr(notice, "a_value_source", "") or ""
            ).lower()
            lineage_missing = (
                notice is None
                or basis_amount <= 0
                or basis_at is None
                or notice_at is None
                or feature_cutoff_at is None
                or notice_method not in KNOWN_METHODS
                or a_source_for_lineage != "tier0"
            )
            if lineage_missing:
                stats._bump(source, "total_seen")
                stats._bump(source, "excluded_feature_lineage_unknown")
                continue
            feature_observed_at = max(basis_at, notice_at)
            if feature_observed_at > feature_cutoff_at:
                stats._bump(source, "total_seen")
                stats._bump(source, "excluded_feature_observed_after_cutoff")
                continue
            basic_price = basis_amount
            bid_method = notice_method
            feature_observation_source = "notice_predeadline+basis_tier0"

        if not _quality_allows(
            basic_price,
            r.winner_price,
            r.reserved_price,
            source=source,
            stats=stats,
            enforce_base_consistency=enforce_base_consistency,
        ):
            continue
        if not r.bid_no or r.bid_no in existing_bid_nos:
            stats._bump(source, "excluded_duplicate")
            continue
        existing_bid_nos.add(r.bid_no)
        notice_lower = float(getattr(notice, "lower_limit_rate", None) or 0)
        stored_llr = (
            notice_lower
            if require_feature_lineage
            else float(getattr(r, "lower_limit_rate", None) or 0)
        )
        contract_type = str(
            getattr(notice, "contract_type", "CONSTRUCTION") or "CONSTRUCTION"
        )
        rule_date = (
            getattr(notice, "start_date", None).date()
            if getattr(notice, "start_date", None)
            else (open_dt.date() if open_dt else None)
        )
        if stored_llr > 0:
            llr = stored_llr
        elif contract_type == "CONSTRUCTION":
            llr = get_lower_limit_rate(
                contract_type,
                basic_price=float(basic_price),
                bid_date=rule_date,
            )
        else:
            stats._bump(source, "excluded_feature_lineage_unknown")
            continue
        a_applicable = str(getattr(notice, "a_value_applicable", "") or "").upper()
        notice_a_value = float(getattr(notice, "a_value", 0) or 0)
        a_value = 0.0 if a_applicable == "N" else max(0.0, notice_a_value)
        if a_applicable == "N":
            a_status = "not_applicable"
        elif a_value > 0 and getattr(notice, "a_value_source", None):
            a_status = "confirmed"
        else:
            a_status = "unknown"
        if require_a_value_status and a_status == "unknown":
            stats._bump(source, "excluded_a_value_unknown")
            continue
        latest_revision = latest_revision_by_bid_no.get(r.bid_no)
        if latest_revision is not None:
            outcome_observed_at = _parse_observed_at(latest_revision.observed_at)
            outcome_observation_source = "opening_result_revision"
            opening_revision = (
                f"{latest_revision.revision_no}:"
                f"{latest_revision.content_hash}:"
                f"{_revision_text(latest_revision.observed_at)}"
            )
        else:
            outcome_observed_at = _parse_observed_at(
                getattr(r, "crawled_at", None)
            )
            outcome_observation_source = (
                "opening_result_crawler" if outcome_observed_at else "unknown"
            )
            opening_revision = _revision_text(getattr(r, "crawled_at", None))
        if require_observation_time and outcome_observed_at is None:
            stats._bump(source, "excluded_observation_time_unknown")
            continue
        notice_revision = _revision_text(
            getattr(notice, "basis_amount_at", None)
            or getattr(notice, "start_date", None)
        )
        a_source = str(getattr(notice, "a_value_source", "") or "none")
        out.append(BidRecord(
            bid_no=r.bid_no,
            title="",
            org=r.organization or "",
            bid_method=bid_method,
            basic_price=float(basic_price),
            estimated_price=float(r.reserved_price or 0),
            reserved_price=float(r.reserved_price),
            winner_price=float(r.winner_price),
            winner_rate=float(r.winner_rate or 0),
            lower_limit_rate=llr,
            year=year,
            a_value=a_value,
            a_value_status=a_status,
            source=source,
            source_revision=(
                f"opening:{opening_revision}|notice:{notice_revision}|"
                f"a:{a_source}:{a_applicable or 'unknown'}"
            ),
            outcome_observed_at=outcome_observed_at,
            outcome_observation_source=outcome_observation_source,
            feature_observed_at=feature_observed_at,
            feature_cutoff_at=feature_cutoff_at,
            feature_observation_source=feature_observation_source,
        ))
        stats._bump(source, "included")
    return out


def load_records(
    year_range: tuple[int, int] = (2021, 2027),
    data_dir: Path = _DATA_DIR,
    db=None,
    *,
    strict_db: bool = False,
    quality_stats: DatasetQualityStats | None = None,
    enforce_base_consistency: bool = False,
    require_a_value_status: bool = False,
    require_observation_time: bool = False,
    require_feature_lineage: bool = False,
) -> list[BidRecord]:
    """opening_results_{year}.json 들을 로드·정제 (+ db 제공 시 누적 DB 병합).

    기본 유효 조건은 기존 호환을 위해 양수 가격이다. 자가보정 학습은
    ``enforce_base_consistency=True``로 예정가격/기초금액 0.94~1.06 계약을
    추가 적용한다. ``require_observation_time=True``이면 개찰일을 관측시각으로
    추정하지 않고 명시적 수집/정정 시각이 없는 행을 fail-closed로 제외한다.
    mock/benchmark는 자체 집계에서 같은 단일 소스를 이미 쓴다.
    db 전달 시 매일 쌓이는 opening_results 테이블도 합쳐 최신 시장 반영.
    운영 판정처럼 DB 누락과 빈 표본을 구분해야 하는 호출부는
    ``strict_db=True``로 조회 오류를 그대로 받는다.
    """
    records: list[BidRecord] = []
    stats = quality_stats or DatasetQualityStats()
    existing_bid_nos: set[str] = set()
    for year in range(year_range[0], year_range[1]):
        f = data_dir / f"opening_results_{year}.json"
        if not f.exists():
            continue
        source = f"static:{f.name}"
        with open(f, encoding="utf-8") as fh:
            items = json.load(fh)
        for item in items:
            bp = (
                item.get("basis_amount", 0)
                if require_feature_lineage
                else item.get("basic_price", 0)
            ) or 0
            wp = item.get("winner_price", 0) or 0
            rp = item.get("reserved_price", 0) or 0
            feature_observed_at = None
            feature_cutoff_at = None
            feature_observation_source = "unknown"
            if require_feature_lineage:
                basis_at = _parse_observed_at(item.get("basis_amount_at"))
                notice_at = _parse_observed_at(item.get("notice_observed_at"))
                feature_cutoff_at = _parse_observed_at(
                    item.get("information_cutoff_at") or item.get("deadline_at")
                )
                if (
                    basis_at is None
                    or notice_at is None
                    or feature_cutoff_at is None
                    or item.get("bid_method") not in KNOWN_METHODS
                    or str(item.get("a_value_source") or "").lower() != "tier0"
                ):
                    stats._bump(source, "total_seen")
                    stats._bump(source, "excluded_feature_lineage_unknown")
                    continue
                feature_observed_at = max(basis_at, notice_at)
                if feature_observed_at > feature_cutoff_at:
                    stats._bump(source, "total_seen")
                    stats._bump(source, "excluded_feature_observed_after_cutoff")
                    continue
                feature_observation_source = "static_predeadline_manifest"
            if not _quality_allows(
                bp,
                wp,
                rp,
                source=source,
                stats=stats,
                enforce_base_consistency=enforce_base_consistency,
            ):
                continue
            bid_no = str(item.get("bid_no", "") or "")
            if not bid_no or bid_no in existing_bid_nos:
                stats._bump(source, "excluded_duplicate")
                continue
            od = item.get("open_date", "")
            y = (
                int(od[:4])
                if od and len(od) >= 4 and od[:4].isdigit()
                else year
            )
            stored_llr = float(item.get("lower_limit_rate", 0) or 0)
            if stored_llr <= 0:
                from app.services.lower_limits import get_lower_limit_rate

                open_date = None
                if od:
                    try:
                        open_date = datetime.fromisoformat(
                            str(od).replace("Z", "+00:00")
                        ).date()
                    except ValueError:
                        open_date = None
                stored_llr = get_lower_limit_rate(
                    "CONSTRUCTION",
                    basic_price=float(bp),
                    bid_date=open_date,
                )
            a_applicable = str(item.get("a_value_applicable", "") or "").upper()
            a_value = float(item.get("a_value", 0) or 0)
            if a_applicable == "N":
                a_status = "not_applicable"
                a_value = 0.0
            elif a_value > 0 and item.get("a_value_source"):
                a_status = "confirmed"
            else:
                a_status = "unknown"
            if require_a_value_status and a_status == "unknown":
                stats._bump(source, "excluded_a_value_unknown")
                continue
            outcome_observed_at, outcome_observation_source = _static_observation(
                item
            )
            if require_observation_time and outcome_observed_at is None:
                stats._bump(source, "excluded_observation_time_unknown")
                continue
            records.append(
                BidRecord(
                    bid_no=bid_no,
                    title=item.get("title", ""),
                    org=item.get("org", ""),
                    bid_method=item.get("bid_method", ""),
                    basic_price=float(bp),
                    estimated_price=float(item.get("estimated_price", 0) or 0),
                    reserved_price=float(rp),
                    winner_price=float(wp),
                    winner_rate=float(item.get("winner_rate", 0) or 0),
                    lower_limit_rate=stored_llr,
                    year=y,
                    a_value=a_value,
                    a_value_status=a_status,
                    source=source,
                    source_revision=str(
                        item.get("revision")
                        or item.get("updated_at")
                        or item.get("crawled_at")
                        or ""
                    ),
                    outcome_observed_at=outcome_observed_at,
                    outcome_observation_source=outcome_observation_source,
                    feature_observed_at=feature_observed_at,
                    feature_cutoff_at=feature_cutoff_at,
                    feature_observation_source=feature_observation_source,
                )
            )
            # 실제 포함된 정적 행만 DB 보정본보다 우선한다. A값 상태 등으로
            # 제외된 정적 행의 ID까지 선점하면 더 완전한 DB 정정본이 막힌다.
            existing_bid_nos.add(bid_no)
            stats._bump(source, "included")
    # 누적 DB 병합 (db 제공 시) — 매일 크롤된 최신 개찰결과 포함
    if db is not None:
        db_records = _load_db_records(
            db,
            set(),
            year_range=year_range,
            strict=strict_db,
            quality_stats=stats,
            enforce_base_consistency=enforce_base_consistency,
            require_a_value_status=require_a_value_status,
            require_observation_time=require_observation_time,
            require_feature_lineage=require_feature_lineage,
        )
        # 정적 export와 DB projection이 같은 공고를 담을 수 있다. 파일을 먼저
        # 읽었다는 이유로 최신 append-only 정정을 버리지 않고 실제 관측시각을
        # 비교한다. 동률이면 revision lineage가 있는 DB 정본을 우선한다.
        record_by_bid_no = {record.bid_no: record for record in records}
        record_index = {
            record.bid_no: index for index, record in enumerate(records)
        }

        def precedence(record: BidRecord) -> tuple[datetime, int, str]:
            observed_at = record.outcome_observed_at or datetime.min.replace(
                tzinfo=timezone.utc
            )
            authority = {
                "opening_result_revision": 3,
                "opening_result_crawler": 2,
            }.get(record.outcome_observation_source, 1)
            return observed_at, authority, record.source_revision

        def mark_superseded(record: BidRecord) -> None:
            stats.included -= 1
            stats.by_source[record.source]["included"] -= 1
            stats._bump(record.source, "excluded_duplicate")

        for db_record in db_records:
            current = record_by_bid_no.get(db_record.bid_no)
            if current is None:
                record_index[db_record.bid_no] = len(records)
                record_by_bid_no[db_record.bid_no] = db_record
                records.append(db_record)
            elif precedence(db_record) > precedence(current):
                mark_superseded(current)
                records[record_index[db_record.bid_no]] = db_record
                record_by_bid_no[db_record.bid_no] = db_record
            else:
                mark_superseded(db_record)
    return records


def data_fingerprint(records: list[BidRecord]) -> str:
    """학습값·출처·정정본에 민감한 canonical content hash."""
    canonical_rows = []
    for record in records:
        row = asdict(record)
        row["outcome_observed_at"] = _revision_text(record.outcome_observed_at)
        canonical_rows.append(
            json.dumps(
                row,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
        )
    canonical_rows.sort()
    payload = "[" + ",".join(canonical_rows) + "]"
    h = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]
    return f"n{len(records)}_{h}"


def filter_segment(
    records: list[BidRecord], method: str, bracket: str
) -> list[BidRecord]:
    """특정 (입찰방법, 금액대) 세그먼트만 추출."""
    return [r for r in records if r.bid_method == method and r.bracket == bracket]


def iter_segments(records: list[BidRecord]) -> list[tuple[str, str]]:
    """데이터에 실제로 존재하는 (method, bracket) 세그먼트 목록."""
    seen = {(r.bid_method, r.bracket) for r in records}
    return sorted(seen)


def split_by_year(
    records: list[BidRecord], holdout_years: tuple[int, ...]
) -> tuple[list[BidRecord], list[BidRecord]]:
    """walk-forward 검증용: (학습셋, hold-out셋) 분리."""
    train = [r for r in records if r.year not in holdout_years]
    holdout = [r for r in records if r.year in holdout_years]
    return train, holdout


def split_temporal_records(
    records: list[BidRecord],
    *,
    validation_years: tuple[int, ...] = (2025,),
    sealed_holdout_years: tuple[int, ...] = (2026,),
    training_cutoff_at: datetime | str | None = None,
    candidate_selected_at: datetime | str | None = None,
    require_known_observation: bool = False,
) -> TemporalSplit:
    """train → validation → sealed holdout을 겹치지 않게 시간순 분리한다.

    연도는 outcome cohort를 정할 뿐, 그 결과가 당시 알려져 있었다는 증거가
    아니다. train 결과는 동결된 training cutoff까지, validation 결과는 후보
    선택시각까지 실제 관측된 경우에만 각각의 집합에 들어간다. sealed 결과가
    후보 선택 전에 이미 관측됐다면 sealed test로 재사용하지 않는다.

    ``require_known_observation=False``는 기존 진단 호출부 호환을 위한 값이다.
    주간 후보 생성은 반드시 True를 사용한다.
    """
    validation = set(validation_years)
    sealed = set(sealed_holdout_years)
    if not validation or not sealed:
        raise ValueError("validation_years와 sealed_holdout_years는 비어 있을 수 없습니다")
    if validation & sealed:
        raise ValueError("validation과 sealed holdout 연도는 겹칠 수 없습니다")
    if max(validation) >= min(sealed):
        raise ValueError("validation은 sealed holdout보다 과거여야 합니다")

    train_year_cutoff = min(validation)
    default_training_cutoff = datetime(
        train_year_cutoff, 1, 1, tzinfo=timezone.utc
    )
    default_candidate_selected = datetime.now(timezone.utc)
    if training_cutoff_at is None:
        frozen_training_cutoff = default_training_cutoff
    else:
        frozen_training_cutoff = _parse_observed_at(training_cutoff_at)
        if frozen_training_cutoff is None:
            raise ValueError("training_cutoff_at은 유효한 datetime이어야 합니다")
    if candidate_selected_at is None:
        frozen_candidate_selected = default_candidate_selected
    else:
        frozen_candidate_selected = _parse_observed_at(candidate_selected_at)
        if frozen_candidate_selected is None:
            raise ValueError("candidate_selected_at은 유효한 datetime이어야 합니다")
    if frozen_training_cutoff >= frozen_candidate_selected:
        raise ValueError("training cutoff는 candidate selection보다 과거여야 합니다")

    train: list[BidRecord] = []
    validation_rows: list[BidRecord] = []
    sealed_rows: list[BidRecord] = []
    excluded: list[BidRecord] = []
    excluded_unknown: list[BidRecord] = []
    excluded_late: list[BidRecord] = []
    excluded_preselected_sealed: list[BidRecord] = []
    for record in records:
        if not (
            0 < record.year < train_year_cutoff
            or record.year in validation
            or record.year in sealed
        ):
            excluded.append(record)
            continue

        observed_at = _parse_observed_at(record.outcome_observed_at)
        if observed_at is None:
            if require_known_observation:
                excluded_unknown.append(record)
                continue
            # 진단용 호환 모드에서는 이전 연도 분리 동작을 유지한다.
            if 0 < record.year < train_year_cutoff:
                train.append(record)
            elif record.year in validation:
                validation_rows.append(record)
            else:
                sealed_rows.append(record)
            continue

        if 0 < record.year < train_year_cutoff:
            if observed_at <= frozen_training_cutoff:
                train.append(record)
            else:
                excluded_late.append(record)
        elif record.year in validation:
            if observed_at <= frozen_candidate_selected:
                validation_rows.append(record)
            else:
                excluded_late.append(record)
        elif observed_at > frozen_candidate_selected:
            sealed_rows.append(record)
        else:
            excluded_preselected_sealed.append(record)

    return TemporalSplit(
        train=train,
        validation=validation_rows,
        sealed_holdout=sealed_rows,
        excluded_out_of_window=excluded,
        excluded_observation_unknown=excluded_unknown,
        excluded_observed_after_cutoff=excluded_late,
        excluded_sealed_before_selection=excluded_preselected_sealed,
        training_cutoff_at=frozen_training_cutoff,
        candidate_selected_at=frozen_candidate_selected,
    )
