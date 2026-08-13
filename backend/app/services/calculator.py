"""
Advanced Bidding Calculator Service
정밀 투찰가 계산 및 안전도 분석
"""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_FLOOR
from enum import Enum

from app.services.lower_limits import LEGACY_RATES, get_lower_limit_rate as _shared_lower_limit


class SafetyLevel(str, Enum):
    SAFE = "SAFE"           # 안전한 투찰 구간
    WARNING = "WARNING"     # 주의 (하한선 근접)
    DANGER = "DANGER"       # 위험 (하한선 미달)


@dataclass
class BidCalculationResult:
    """상세 계산 결과"""
    original_price: float           # 기초금액
    rate: float                     # 사정률 (%)
    result_price: int               # 투찰금액 (10원 미만 절사)
    
    # 예정가격 정보
    estimated_price_min: float | None
    estimated_price_max: float | None
    
    # 하한선 정보
    lower_limit_rate: float         # 낙찰하한율 (%)
    lower_limit_price: int          # 낙찰하한선 금액 (기초금액 기준)
    lower_limit_price_est_min: int | None
    lower_limit_price_est_max: int | None
    
    # A값 정보
    a_value: int                    # A값 (국민연금, 건강보험 등 고정비)
    a_value_applied: bool           # A값 적용 여부
    
    # 안전도
    safety_level: SafetyLevel
    distance_from_limit: float      # 하한선 대비 여유율 (%)
    
    # 메시지
    warning_message: str | None = None


# 법정 낙찰하한선 — 정본은 app.services.lower_limits (2026-07-17 통합).
# 이 별칭은 하위 호환용. 공사는 금액대·시행일 티어드라 상수 참조 대신
# CalculatorService.get_lower_limit_rate(contract_type, basic_price) 를 쓸 것.
LOWER_LIMIT_RATES = LEGACY_RATES

# 입찰방법 + 금액대별 최적 전략
# 5년치 4,848건 가중 그리드 서치 (최근 연도 가중치 3x, 하한통과 90%+)
# (예정가격 보정%, 하한선 여유분%p)
BID_STRATEGY = {
    "적격심사제": {
        "small":   (-1.0, 1.4),   # 1억 미만 (54건): 낙찰 55.4%, 통과 92.4%
        "medium":  (+0.7, 0.2),   # 1~5억 (619건): 낙찰 30.6%, 통과 92.0%
        "large":   (-0.9, 1.5),   # 5~10억 (204건): 낙찰 31.8%, 통과 90.2%
        "xlarge":  (-0.2, 0.9),   # 10~50억 (189건): 낙찰 5.4%, 통과 92.5%
        "xxlarge": (-0.7, 1.5),   # 50억+ (51건): 낙찰 2.7%, 통과 93.2%
    },
    "소액수의견적": {
        "small":   (-0.2, 0.9),   # 1억 미만 (2575건): 낙찰 12.9%, 통과 90.4%
        "medium":  (+0.6, 0.3),   # 1~5억 (1096건): 낙찰 15.2%, 통과 91.9%
        "large":   (+0.6, 0.3),   # 5억+ 표본 부족, medium과 동일
        "xlarge":  (+0.6, 0.3),
        "xxlarge": (+0.6, 0.3),
    },
    "DEFAULT": {
        "small":   (-0.3, 1.0),
        "medium":  (+0.5, 0.3),
        "large":   (-0.3, 1.0),
        "xlarge":  (-0.2, 0.9),
        "xxlarge": (-0.5, 1.2),
    },
}


def _get_price_bracket(basic_price: float) -> str:
    """기초금액으로 금액대 구분 (5단계)"""
    if basic_price < 1e8:
        return "small"       # 1억 미만
    elif basic_price < 5e8:
        return "medium"      # 1~5억
    elif basic_price < 1e9:
        return "large"       # 5~10억
    elif basic_price < 5e9:
        return "xlarge"      # 10~50억
    else:
        return "xxlarge"     # 50억 이상


# ── 동적 전략 파라미터 로딩 ─────────────────────────────────
# BID_STRATEGY(위)는 부트스트랩 기본값. 실제 운영 파라미터는
# autocalibrate.strategy_store 의 버전 관리 저장소에서 동적 조회한다.
# 저장소 접근 실패 시 BID_STRATEGY 로 안전하게 폴백.
_strategy_cache: dict | None = None
_strategy_mtime: float | None = None
_strategy_version_cache: str | None = None
_strategy_parameters_hash_cache: str | None = None
_strategy_data_manifest_hash_cache: str | None = None


def _get_active_strategy_snapshot() -> tuple[dict, str, str, str | None]:
    """한 번 읽은 active 전략과 그 provenance를 같은 snapshot으로 반환한다."""
    global _strategy_cache, _strategy_mtime, _strategy_version_cache
    global _strategy_parameters_hash_cache, _strategy_data_manifest_hash_cache
    try:
        from app.services.autocalibrate.strategy_store import (
            get_default_store,
            strategy_parameters_hash,
        )

        store = get_default_store()
        store.ensure_bootstrap(BID_STRATEGY)  # 최초 1회 v0_bootstrap 저장
        mtime = store.active_mtime()
        if _strategy_cache is None or mtime != _strategy_mtime:
            active = store.load_active()
            _strategy_cache = active.params
            _strategy_version_cache = active.version_id
            _strategy_parameters_hash_cache = strategy_parameters_hash(active.params)
            _strategy_data_manifest_hash_cache = getattr(
                active, "data_manifest_hash", None
            )
            _strategy_mtime = mtime
        return (
            _strategy_cache,
            _strategy_version_cache or "unknown",
            _strategy_parameters_hash_cache or strategy_parameters_hash(_strategy_cache),
            _strategy_data_manifest_hash_cache,
        )
    except Exception:
        # 저장소 미초기화/오류 시 정적 기본값으로 폴백
        from app.services.autocalibrate.strategy_store import strategy_parameters_hash

        return (
            BID_STRATEGY,
            "v0_static_fallback",
            strategy_parameters_hash(BID_STRATEGY),
            None,
        )


def _get_active_strategy() -> dict:
    """하위 호환용 파라미터 조회. 추천은 snapshot API를 직접 사용한다."""
    return _get_active_strategy_snapshot()[0]


def reload_strategy_cache() -> None:
    """전략 캐시 강제 무효화 (자가보정 사이클 채택 직후 호출용)."""
    global _strategy_cache, _strategy_mtime, _strategy_version_cache
    global _strategy_parameters_hash_cache, _strategy_data_manifest_hash_cache
    _strategy_cache = None
    _strategy_mtime = None
    _strategy_version_cache = None
    _strategy_parameters_hash_cache = None
    _strategy_data_manifest_hash_cache = None


class CalculatorService:
    
    @staticmethod
    def get_lower_limit_rate(
        contract_type: str,
        basic_price: float | None = None,
        bid_date=None,
    ) -> float:
        """법정 낙찰하한율 조회 (정본: app.services.lower_limits).

        공사는 금액대·시행일(2026-01-30 개정)별 티어드 — basic_price 를
        전달해야 정확하다. 미전달 시 legacy 상수 폴백(하위 호환).
        """
        return _shared_lower_limit(contract_type, basic_price, bid_date)
    
    @staticmethod
    def truncate_to_10_won(price: float) -> int:
        """10원 단위 절사 (10원 미만 버림)."""
        amount = price if isinstance(price, Decimal) else Decimal(str(price))
        return int(
            (amount / Decimal("10")).to_integral_value(rounding=ROUND_FLOOR)
            * Decimal("10")
        )

    @staticmethod
    def calculate_price_at_rate(
        reference_price: float,
        rate_pct: float,
        a_value: float = 0,
    ) -> int:
        """``(reference-A) * rate + A``를 십진수로 계산해 10원 절사한다.

        금액·비율을 이진 부동소수점으로 곱한 뒤 ``floor``하면
        정확히 10원 경계인 값이 9.999999원으로 표현돼 10원이
        더 깎일 수 있다. 외부 입력을 문자열 기반 Decimal로 변환해
        공고 공식의 십진 의미를 보존한다.
        """
        reference = Decimal(str(reference_price))
        fixed = Decimal(str(a_value))
        rate = Decimal(str(rate_pct)) / Decimal("100")
        raw = ((reference - fixed) * rate) + fixed
        return CalculatorService.truncate_to_10_won(raw)
    
    @staticmethod
    def calculate_safe_bid(basic_price: float, rate: float, a_value: float = 0) -> int:
        """
        투찰금액 계산 (A값 반영)
        
        Args:
            basic_price: 기초금액
            rate: 사정률 (예: -5.0 = 기초금액의 95%)
            a_value: A값 (고정비용, 낙찰률 미적용)
        
        Formula:
            A값이 있는 경우: ((기초금액 - A값) * 사정률) + A값
            A값이 없는 경우: 기초금액 * 사정률
        """
        return CalculatorService.calculate_price_at_rate(
            basic_price,
            100 + rate,
            a_value,
        )

    @staticmethod
    def calculate_strategy_price(
        basic_price: float,
        adjustment_pct: float,
        target_rate_pct: float,
        a_value: float = 0,
    ) -> int:
        """Authoritative strategy formula for production and evaluation."""
        basic = Decimal(str(basic_price))
        adjustment = Decimal(str(adjustment_pct)) / Decimal("100")
        predicted_reserved = basic * (Decimal("1") + adjustment)
        return CalculatorService.calculate_price_at_rate(
            predicted_reserved,
            target_rate_pct,
            a_value,
        )
    
    @staticmethod
    def calculate_detailed_bid(
        basic_price: float, 
        rate: float, 
        contract_type: str = "CONSTRUCTION",
        a_value: int = 0,
        *,
        lower_limit_rate: float | None = None,
        bid_date: date | None = None,
        prdprc_range_bgn: float | None = None,
        prdprc_range_end: float | None = None,
    ) -> BidCalculationResult:
        """
        상세 투찰금액 계산 (A값 반영)
        
        Args:
            basic_price: 기초금액
            rate: 사정률 (%)
            contract_type: 계약 유형
            a_value: A값 (고정비용, 낙찰률 미적용)
            lower_limit_rate: 공고가 명시한 낙찰하한율. 공사도 이 값이
                있으면 금액대 표보다 우선한다.
            bid_date: 공사 하한율 시행일 판단 기준일
            prdprc_range_bgn/end: 공고가 명시한 예정가격 범위(%)
        
        Returns:
            BidCalculationResult with all calculation details
        """
        if basic_price <= 0:
            raise ValueError("기초금액은 0보다 커야 합니다")
        if a_value < 0 or a_value >= basic_price:
            raise ValueError("A값은 0 이상 기초금액 미만이어야 합니다")

        normalized_contract = (contract_type or "").strip().upper()
        explicit_lower = (
            float(lower_limit_rate) if lower_limit_rate is not None else None
        )
        if explicit_lower is not None and not 0 < explicit_lower <= 100:
            raise ValueError("낙찰하한율은 0 초과 100 이하여야 합니다")
        if normalized_contract != "CONSTRUCTION" and explicit_lower is None:
            raise ValueError(
                "용역·물품 계산에는 공고가 명시한 낙찰하한율이 필요합니다"
            )
        if (prdprc_range_bgn is None) != (prdprc_range_end is None):
            raise ValueError("예정가격 범위의 시작·끝 값을 함께 입력해야 합니다")
        if (
            prdprc_range_bgn is not None
            and prdprc_range_end is not None
            and prdprc_range_bgn > prdprc_range_end
        ):
            raise ValueError("예정가격 범위 시작값이 끝값보다 클 수 없습니다")

        # 1. 투찰금액 계산 (A값 반영)
        result_price = CalculatorService.calculate_safe_bid(basic_price, rate, a_value)
        
        # 2. 공고가 밝힌 예정가격 범위만 계산한다. ±3%를 임의 대입하지 않는다.
        est_min = (
            basic_price * (1 + prdprc_range_bgn / 100)
            if prdprc_range_bgn is not None
            else None
        )
        est_max = (
            basic_price * (1 + prdprc_range_end / 100)
            if prdprc_range_end is not None
            else None
        )
        
        # 3. 낙찰하한선 계산 (A값 반영). 공고 명시값이 표보다 우선한다.
        lower_rate = (
            explicit_lower
            if explicit_lower is not None
            else CalculatorService.get_lower_limit_rate(
                normalized_contract, basic_price, bid_date
            )
        )
        
        # 기초금액 기준 하한선 (A값 적용 공식: (기초금액 - A) * 하한율 + A)
        limit_base = CalculatorService.calculate_price_at_rate(
            basic_price,
            lower_rate,
            a_value,
        )
        limit_est_min = (
            CalculatorService.calculate_price_at_rate(
                est_min,
                lower_rate,
                a_value,
            )
            if est_min is not None
            else None
        )
        limit_est_max = (
            CalculatorService.calculate_price_at_rate(
                est_max,
                lower_rate,
                a_value,
            )
            if est_max is not None
            else None
        )
        
        # 4. 안전도 계산
        # 기초금액 기준 하한선으로 판단 (보수적)
        if result_price < limit_base:
            safety_level = SafetyLevel.DANGER
            warning_msg = f"투찰금액이 낙찰하한선 미만입니다. ({lower_rate}% = {limit_base:,}원)"
        elif result_price < limit_base * 1.02:  # 하한선 +2% 이내
            safety_level = SafetyLevel.WARNING
            warning_msg = f"낙찰하한선({lower_rate}%)에 매우 근접합니다. 주의하세요."
        else:
            safety_level = SafetyLevel.SAFE
            warning_msg = None
        
        # 하한선 대비 여유율 계산
        if limit_base > 0:
            distance = ((result_price - limit_base) / limit_base) * 100
        else:
            distance = 100.0  # 하한선 없음
        
        return BidCalculationResult(
            original_price=basic_price,
            rate=rate,
            result_price=result_price,
            estimated_price_min=est_min,
            estimated_price_max=est_max,
            lower_limit_rate=lower_rate,
            lower_limit_price=limit_base,
            lower_limit_price_est_min=limit_est_min,
            lower_limit_price_est_max=limit_est_max,
            a_value=a_value,
            a_value_applied=a_value > 0,
            safety_level=safety_level,
            distance_from_limit=round(distance, 2),
            warning_message=warning_msg,
        )
    
    @staticmethod
    def get_rate_for_target_price(basic_price: float, target_price: float) -> float:
        """
        목표 투찰금액에 필요한 사정률 역산
        
        Args:
            basic_price: 기초금액
            target_price: 목표 투찰금액
        
        Returns:
            사정률 (%)
        """
        if basic_price <= 0:
            return 0.0
        return ((target_price / basic_price) - 1) * 100
    
    @staticmethod
    def get_safe_rate_range(
        basic_price: float,
        contract_type: str = "CONSTRUCTION"
    ) -> tuple[float, float]:
        """
        안전한 사정률 범위 계산

        Returns:
            (최소 사정률, 최대 사정률)
        """
        lower_rate = CalculatorService.get_lower_limit_rate(contract_type, basic_price)

        # 하한선 기준 최소 사정률
        min_rate = lower_rate - 100  # 예: 87.745 - 100 = -12.255%

        # 일반적인 최대 사정률 (예정가격 근처)
        max_rate = 5.0  # +5% 정도가 현실적 상한

        return (round(min_rate, 3), max_rate)

    @staticmethod
    def recommend_bid_price(
        basic_price: float,
        bid_method: str = "DEFAULT",
        contract_type: str = "CONSTRUCTION",
        a_value: float = 0,
        strategy_override: dict | None = None,
        *,
        lower_limit_rate: float | None = None,
        bid_date: date | None = None,
    ) -> dict:
        """
        입찰방법 + 금액대별 최적 투찰가 추천 (실전용)

        문제지(기초금액, 입찰방법)만 보고 투찰가를 결정한다.
        예정가격은 모르는 상태 — 과거 데이터 기반으로:
        1. 예정가격 보정: 기초금액에 보정값을 적용
        2. 여유분 적용: 하한율 위에 최적 여유분 추가

        Args:
            basic_price: 기초금액
            bid_method: 입찰방법 (적격심사제, 소액수의견적 등)
            contract_type: 계약유형 (CONSTRUCTION, SERVICE, GOODS)
            a_value: A값 (고정비용)
            strategy_override: 임의 파라미터셋 주입 (백테스트/최적화/가드 검증용).
                None 이면 autocalibrate 저장소의 active 파라미터 사용.
            lower_limit_rate: 공고가 명시한 낙찰하한율. 주어지면 공통
                표 계산값보다 우선한다.
            bid_date: 명시 하한율이 없을 때 공사 하한율 시행일을
                판단할 기준일.

        Returns:
            dict with recommended_price, bid_rate, margin, strategy_desc
        """
        if basic_price <= 0:
            raise ValueError("기초금액은 0보다 커야 합니다")
        if a_value < 0 or a_value >= basic_price:
            raise ValueError("A값은 0 이상 기초금액 미만이어야 합니다")

        explicit_lower = (
            float(lower_limit_rate) if lower_limit_rate is not None else None
        )
        if explicit_lower is not None and not 0 < explicit_lower <= 100:
            raise ValueError("낙찰하한율은 0 초과 100 이하여야 합니다")
        lower_rate = (
            explicit_lower
            if explicit_lower is not None
            else CalculatorService.get_lower_limit_rate(
                contract_type, basic_price, bid_date
            )
        )
        bracket = _get_price_bracket(basic_price)

        # 입찰방법 + 금액대별 최적 파라미터 조회 (동적 또는 주입)
        if strategy_override is not None:
            from app.services.autocalibrate.strategy_store import strategy_parameters_hash

            strategy = strategy_override
            strategy_version = "strategy_override"
            parameters_hash = strategy_parameters_hash(strategy_override)
            data_manifest_hash = None
        else:
            (
                strategy,
                strategy_version,
                parameters_hash,
                data_manifest_hash,
            ) = _get_active_strategy_snapshot()
        default_method = strategy.get("DEFAULT", BID_STRATEGY["DEFAULT"])
        method_strategy = strategy.get(bid_method, default_method)
        _params = method_strategy.get(bracket, (-0.3, 1.0))
        # JSON 저장소는 list, 정적 딕셔너리는 tuple — 둘 다 호환
        adjustment, margin = float(_params[0]), float(_params[1])

        # 예정가격 예측: 기초금액에 보정값 적용. 금액 경계에서
        # 이진 float 오차로 10원이 더 절사되지 않도록 Decimal을 유지한다.
        basic_decimal = Decimal(str(basic_price))
        a_decimal = Decimal(str(a_value))
        adjustment_decimal = Decimal(str(adjustment)) / Decimal("100")
        predicted_reserved = basic_decimal * (Decimal("1") + adjustment_decimal)
        if a_decimal >= predicted_reserved:
            raise ValueError("A값은 보정 예정가격 미만이어야 합니다")

        # 투찰률 = 하한율 + 여유분
        target_rate_pct = lower_rate + margin

        recommended_price = CalculatorService.calculate_strategy_price(
            basic_price,
            adjustment,
            target_rate_pct,
            a_value,
        )
        bid_rate = (recommended_price / basic_price) * 100 if basic_price > 0 else 0

        return {
            "recommended_price": recommended_price,
            "bid_rate": round(bid_rate, 4),
            "lower_limit_rate": lower_rate,
            "margin": margin,
            "adjustment": adjustment,
            "strategy_version": strategy_version,
            "strategy_parameters_hash": parameters_hash,
            "data_manifest_hash": data_manifest_hash,
            "predicted_reserved_price": float(predicted_reserved),
            "bracket": bracket,
            "target_rate_pct": round(target_rate_pct, 3),
            "bid_method": bid_method,
            "strategy_desc": (
                f"[{bracket}] 보정 {adjustment:+.1f}%, "
                f"하한율 {lower_rate}% + 여유분 {margin}%p = {target_rate_pct:.3f}%"
            ),
        }
