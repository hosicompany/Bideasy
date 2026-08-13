"""
Rule-based Tips Generator for Bid Analysis
환각(Hallucination) 방지를 위해 데이터 기반으로만 팁 생성

모든 팁은 다음 중 하나의 출처를 가짐:
- "API 데이터": 공공데이터포털에서 직접 가져온 정보
- "법률 기반": 국가계약법 등 법률에 명시된 정보
- "계산값": 수학적 계산으로 도출된 정보
"""

from datetime import datetime
from typing import Dict, List, Optional, Any
from dataclasses import dataclass


@dataclass
class BidTip:
    """입찰 전략 팁"""
    category: str      # eligibility, deadline, price, restriction, document, strategy
    icon: str          # 이모지
    title: str         # 팁 제목
    content: str       # 팁 내용
    source: str        # 데이터 출처
    importance: str    # HIGH, MEDIUM, LOW
    for_beginners: Optional[str] = None  # 초보자용 추가 설명


class TipsGenerator:
    """규칙 기반 입찰 전략 팁 생성기"""
    
    def __init__(self, bid_data: Dict[str, Any], user_profile: Optional[Dict[str, Any]] = None):
        self.data = bid_data
        self.user_profile = user_profile
        self.tips: List[BidTip] = []
    
    def generate_all_tips(self) -> Dict[str, Any]:
        """모든 팁 생성 및 분석 결과 반환"""
        # 맞춤형 분석 (최우선)
        self._generate_personalization_tips()
        
        # 각 카테고리별 팁 생성
        self._generate_eligibility_tips()
        self._generate_deadline_tips()
        self._generate_price_tips()
        self._generate_restriction_tips()
        self._generate_document_tips()
        self._generate_strategy_tips()
        
        # 결과 구성
        return {
            "summary": self._generate_summary(),
            "eligibility": self._get_eligibility_status(),
            "tips": [self._tip_to_dict(tip) for tip in self.tips],
            "deadline_info": self._get_deadline_info(),
            "price_info": self._get_price_info(),
            "meta": {
                "generated_at": datetime.now().isoformat(),
                "tip_count": len(self.tips),
                "data_source": "공공데이터포털 API"
            }
        }
    
    def _tip_to_dict(self, tip: BidTip) -> Dict:
        return {
            "category": tip.category,
            "icon": tip.icon,
            "title": tip.title,
            "content": tip.content,
            "source": tip.source,
            "importance": tip.importance,
            "for_beginners": tip.for_beginners
        }
    
    def _generate_summary(self) -> str:
        """공고 한줄 요약 (데이터 기반)"""
        title = self.data.get("title", "제목 없음")
        org = self.data.get("organization", "")
        basis = self._confirmed_basis()
        estimate = self._safe_float(self.data.get("estimated_price"))
        
        contract_method = self.data.get("contract_method", "")
        
        summary = f"{org}에서 발주한 '{title[:30]}...' 공고입니다. "
        if basis is not None:
            summary += f"확정 기초금액 {basis:,.0f}원"
        elif estimate > 0:
            summary += f"추정가격 {estimate:,.0f}원(기초금액 미확인)"
        else:
            summary += "금액 미상"
        if contract_method:
            summary += f", {contract_method} 방식입니다."
        else:
            summary += "입니다."
        
        return summary
    
    def _get_eligibility_status(self) -> Dict:
        """참가 자격 상태"""
        issues = []
        
        if self.data.get("sme_only") == "Y":
            issues.append("중소기업만 참가 가능")
        
        if self.data.get("region"):
            issues.append(f"지역제한: {self.data.get('region')}")
        
        if self.data.get("international_bid") == "Y":
            issues.append("국제입찰")
        
        return {
            "can_participate": len(issues) == 0 or None,  # 자격확인 필요
            "requirements": issues,
            "source": "API 데이터"
        }
    
    def _get_deadline_info(self) -> Dict:
        """마감 정보"""
        end_date = self.data.get("end_date")
        opening_date = self.data.get("opening_date")
        
        days_left = None
        if end_date:
            try:
                if isinstance(end_date, str):
                    end_dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
                else:
                    end_dt = end_date
                days_left = (end_dt - datetime.now()).days
            except Exception:
                pass
        
        return {
            "end_date": str(end_date) if end_date else None,
            "opening_date": opening_date,
            "days_remaining": days_left,
            "is_urgent": days_left is not None and days_left <= 3,
            "source": "API 데이터 + 계산값"
        }
    
    def _safe_float(self, value: Any) -> float:
        """안전한 float 변환 (쉼표 처리)"""
        if value is None:
            return 0.0
        try:
            if isinstance(value, (int, float)):
                return float(value)
            # 문자열인 경우 쉼표 제거
            return float(str(value).replace(",", "").strip())
        except (ValueError, TypeError):
            return 0.0

    def _confirmed_basis(self) -> float | None:
        """Return only an explicitly confirmed basis amount.

        ``basic_price`` is intentionally ignored: historical callers used the
        name for presmptPrce, which is an estimate on a different VAT basis.
        """
        if str(self.data.get("basis_status") or "").lower() != "confirmed":
            return None
        value = self._safe_float(self.data.get("basis_amount"))
        return value if value > 0 else None

    def _contract_type(self) -> str:
        raw = str(self.data.get("contract_type") or "").strip().upper()
        if raw in {"CONSTRUCTION", "WORKS", "공사"}:
            return "CONSTRUCTION"
        if raw in {"SERVICE", "용역"}:
            return "SERVICE"
        if raw in {"GOODS", "물품"}:
            return "GOODS"
        return "UNKNOWN"

    def _a_value_context(self, basis: float) -> tuple[int | None, str]:
        applicable = str(self.data.get("a_value_applicable") or "").strip().upper()
        value = int(self._safe_float(self.data.get("a_value")))
        source = str(self.data.get("a_value_source") or "").strip()

        if applicable in {"N", "NO", "FALSE", "미적용", "비대상"}:
            if value > 0:
                return None, "invalid"
            return 0, "not_applicable"
        if value > 0 and source:
            if value >= basis:
                return None, "invalid"
            return value, "confirmed"
        return None, "unknown"

    def _get_price_info(self) -> Dict:
        """가격 정보. 확인되지 않은 금액으로 안전 수치를 만들지 않는다."""
        basis = self._confirmed_basis()
        estimate = self._safe_float(self.data.get("estimated_price"))
        budget = self.data.get("budget_amount", 0)
        contract_type = self._contract_type()

        result: Dict[str, Any] = {
            "basis_status": "confirmed" if basis is not None else "unconfirmed",
            "basic_price": basis,
            "basic_price_formatted": f"{basis:,.0f}원" if basis is not None else None,
            "estimated_price": estimate if estimate > 0 else None,
            "estimated_price_formatted": f"{estimate:,.0f}원" if estimate > 0 else None,
            "estimated_price_range": None,
            "lower_limit": None,
            "budget": self._safe_float(budget),
            "source": "공공데이터 API + 확정값 기반 계산",
        }
        if basis is None:
            result["abstain_reason"] = (
                "확정 기초금액이 없어 가격·하한 계산을 보류합니다. "
                "추정가격을 기초금액으로 대체하지 않습니다."
            )
            return result

        try:
            range_bgn = self.data.get("prdprc_range_bgn")
            range_end = self.data.get("prdprc_range_end")
            if range_bgn is not None and range_end is not None:
                low = self._safe_float(range_bgn)
                high = self._safe_float(range_end)
                if low <= high:
                    est_min = basis * (1 + low / 100)
                    est_max = basis * (1 + high / 100)
                    result["estimated_price_range"] = {
                        "min": est_min,
                        "max": est_max,
                        "min_formatted": f"{est_min:,.0f}원",
                        "max_formatted": f"{est_max:,.0f}원",
                        "range_bgn": low,
                        "range_end": high,
                    }

            if contract_type == "UNKNOWN":
                result["abstain_reason"] = "계약 유형을 확인하지 못해 하한 계산을 보류합니다."
                return result

            a_value, a_status = self._a_value_context(basis)
            result["a_value_status"] = a_status
            if a_value is None:
                result["abstain_reason"] = (
                    "A값 산정 대상 여부 또는 확정 A값을 확인하지 못해 하한 계산을 보류합니다."
                    if a_status == "unknown"
                    else "A값은 0 이상이며 기초금액보다 작아야 합니다."
                )
                return result

            lower_rate = self.data.get("lower_limit_rate")
            if lower_rate is None:
                result["abstain_reason"] = (
                    "공고가 명시한 낙찰하한율을 확인하지 못해 하한 계산을 보류합니다."
                )
                return result

            from app.services.calculator import CalculatorService

            calculated = CalculatorService.calculate_detailed_bid(
                basic_price=basis,
                rate=0,
                contract_type=contract_type,
                a_value=a_value,
                lower_limit_rate=self._safe_float(lower_rate),
                prdprc_range_bgn=(
                    self._safe_float(range_bgn) if range_bgn is not None else None
                ),
                prdprc_range_end=(
                    self._safe_float(range_end) if range_end is not None else None
                ),
            )
            result["lower_limit"] = {
                "rate": calculated.lower_limit_rate,
                "amount": calculated.lower_limit_price,
                "formatted": f"{calculated.lower_limit_price:,.0f}원",
            }
            return result
        except Exception as e:
            result["error"] = f"가격 계산 오류: {str(e)}"
            result["abstain_reason"] = "가격 입력 검증에 실패해 계산을 보류합니다."
            return result
    
    # ==================== 팁 생성 메서드들 ====================
    
    def _generate_eligibility_tips(self):
        """자격 요건 관련 팁"""
        
        # 중소기업 제한
        if self.data.get("sme_only") == "Y":
            self.tips.append(BidTip(
                category="eligibility",
                icon="🏢",
                title="중소기업 제한 공고",
                content="이 공고는 중소기업만 참가할 수 있습니다. 귀사가 중소기업에 해당하는지 확인하세요.",
                source="API 데이터",
                importance="HIGH",
                for_beginners="중소기업이란 '중소기업기본법'에서 정한 기준(업종별 매출액, 자산총액 등)을 충족하는 기업입니다. 중소기업확인서를 통해 증명할 수 있습니다."
            ))
        
        # 대기업 참여 가능
        if self.data.get("big_company_ok") == "Y":
            self.tips.append(BidTip(
                category="eligibility",
                icon="🏗️",
                title="대기업 참여 가능",
                content="이 공고는 대기업도 참가할 수 있습니다. 경쟁이 치열할 수 있습니다.",
                source="API 데이터",
                importance="MEDIUM"
            ))
        
        # 공동계약 가능
        if self.data.get("joint_contract") == "Y":
            self.tips.append(BidTip(
                category="eligibility",
                icon="🤝",
                title="공동계약(컨소시엄) 가능",
                content="공동도급이 가능한 공고입니다. 단독 참가가 어려운 경우 다른 업체와 컨소시엄을 구성하여 참가할 수 있습니다.",
                source="API 데이터",
                importance="MEDIUM",
                for_beginners="공동계약(공동도급)이란 2개 이상의 기업이 함께 계약을 체결하는 방식입니다. 각 참여 업체의 지분 비율을 합의하여 참가합니다."
            ))
    
    def _generate_deadline_tips(self):
        """일정 관련 팁"""
        deadline_info = self._get_deadline_info()
        days_left = deadline_info.get("days_remaining")
        
        if days_left is not None:
            if days_left <= 0:
                self.tips.append(BidTip(
                    category="deadline",
                    icon="⛔",
                    title="입찰 마감",
                    content="이 공고는 이미 입찰이 마감되었습니다.",
                    source="계산값",
                    importance="HIGH"
                ))
            elif days_left <= 2:
                self.tips.append(BidTip(
                    category="deadline",
                    icon="🚨",
                    title=f"긴급! 마감 {days_left}일 전",
                    content=f"입찰 마감까지 {days_left}일 남았습니다. 서류 준비와 투찰을 서둘러야 합니다.",
                    source="계산값",
                    importance="HIGH",
                    for_beginners="나라장터(G2B) 입찰은 마감 시간 정각에 마감됩니다. 시스템 오류에 대비해 최소 1시간 전에 투찰을 완료하세요."
                ))
            elif days_left <= 5:
                self.tips.append(BidTip(
                    category="deadline",
                    icon="⏰",
                    title=f"마감 {days_left}일 전",
                    content=f"입찰 마감까지 {days_left}일 남았습니다. 공고 규격서를 꼼꼼히 검토하세요.",
                    source="계산값",
                    importance="MEDIUM"
                ))
            else:
                self.tips.append(BidTip(
                    category="deadline",
                    icon="📅",
                    title=f"마감 {days_left}일 전",
                    content=f"입찰 마감까지 {days_left}일 남았습니다. 충분한 검토 시간이 있습니다.",
                    source="계산값",
                    importance="LOW"
                ))
        
        # 개찰일 정보
        opening = deadline_info.get("opening_date")
        if opening:
            self.tips.append(BidTip(
                category="deadline",
                icon="📬",
                title="개찰 일시",
                content=f"개찰 예정: {opening}",
                source="API 데이터",
                importance="LOW",
                for_beginners="개찰이란 투찰된 입찰서를 열어 낙찰자를 결정하는 절차입니다. 개찰 결과는 나라장터에서 확인할 수 있습니다."
            ))
    
    def _generate_price_tips(self):
        """가격 관련 팁"""
        price_info = self._get_price_info()

        abstain_reason = price_info.get("abstain_reason")
        if abstain_reason:
            self.tips.append(BidTip(
                category="price",
                icon="⚠️",
                title="가격 안전 판정 보류",
                content=abstain_reason,
                source="입력 완전성 검증",
                importance="HIGH",
                for_beginners=(
                    "기초금액·A값 적용 여부·공고별 하한율 중 하나라도 확인되지 않으면 "
                    "그럴듯한 기본값으로 채우지 않고 계산을 멈춥니다."
                ),
            ))

        if "error" not in price_info:
            lower_limit = price_info.get("lower_limit") or {}
            est_range = price_info.get("estimated_price_range") or {}
            
            # 예정가격 범위 안내
            if est_range:
                self.tips.append(BidTip(
                    category="price",
                    icon="💰",
                    title="예정가격 범위",
                    content=(
                        "공고가 명시한 복수예비가격 범위를 확정 기초금액에 적용한 값입니다."
                        f"\n• 최소: {est_range.get('min_formatted')}"
                        f"\n• 최대: {est_range.get('max_formatted')}"
                    ),
                    source="공고 명시 범위 + 확정 기초금액",
                    importance="HIGH",
                    for_beginners=(
                        "예정가격 범위는 공고마다 다를 수 있습니다. 범위가 공개되지 않은 "
                        "공고에는 임의의 ±3%를 적용하지 않습니다."
                    ),
                ))
            
            # 낙찰하한선 안내
            if lower_limit.get("rate", 0) > 0:
                self.tips.append(BidTip(
                    category="price",
                    icon="📉",
                    title="공고 명시 낙찰하한선",
                    content=(
                        f"이 공고의 낙찰하한율은 {lower_limit.get('rate')}%이며, "
                        f"확정 입력 기준 하한금액은 {lower_limit.get('formatted')}입니다."
                    ),
                    source="공고 명시 하한율 + 확정 입력 계산",
                    importance="HIGH",
                    for_beginners=(
                        "하한미달, 입찰무효, 적격탈락은 서로 다른 상태입니다. "
                        "가격 하한 통과만으로 최종 낙찰이 보장되지는 않습니다."
                    ),
                ))
    
    def _generate_restriction_tips(self):
        """제한 사항 관련 팁"""
        
        # 지역 제한
        region = self.data.get("region")
        if region:
            self.tips.append(BidTip(
                category="restriction",
                icon="📍",
                title="지역 제한",
                content=f"이 공고는 '{region}' 지역에 소재한 업체만 참가할 수 있습니다.",
                source="API 데이터",
                importance="HIGH",
                for_beginners="지역제한 입찰은 특정 지역에 본사 또는 영업소가 있는 업체만 참가할 수 있습니다. 사업자등록증 주소를 기준으로 판단합니다."
            ))
        
        # 긴급 공고
        if self.data.get("emergency_bid") == "Y":
            self.tips.append(BidTip(
                category="restriction",
                icon="⚡",
                title="긴급 공고",
                content="이 공고는 긴급 공고입니다. 일반 공고보다 입찰 기간이 짧을 수 있습니다.",
                source="API 데이터",
                importance="MEDIUM"
            ))
        
        # 재입찰
        if self.data.get("rebid_yn") == "Y":
            self.tips.append(BidTip(
                category="restriction",
                icon="🔄",
                title="재입찰 공고",
                content="이 공고는 재입찰 공고입니다. 이전 입찰이 유찰되어 다시 공고된 것입니다.",
                source="API 데이터",
                importance="MEDIUM",
                for_beginners="재입찰이란 이전 입찰에서 유효한 입찰자가 2인 미만이거나 다른 사유로 유찰되어 다시 진행하는 입찰입니다. 조건이 변경되었을 수 있으니 규격서를 다시 확인하세요."
            ))
    
    def _generate_document_tips(self):
        """서류 관련 팁"""
        
        # 첨부파일 안내
        attachment_url = self.data.get("attachment_url")
        attachment_name = self.data.get("attachment_name")
        
        if attachment_url:
            self.tips.append(BidTip(
                category="document",
                icon="📎",
                title="공고 규격서 확인 필수",
                content=f"첨부된 규격서 '{attachment_name or '공고규격서'}'를 반드시 다운로드하여 상세 조건을 확인하세요.",
                source="API 데이터",
                importance="HIGH",
                for_beginners="공고 규격서에는 상세한 입찰 조건, 제출 서류, 평가 기준 등이 포함되어 있습니다. 투찰 전 반드시 확인해야 실격을 피할 수 있습니다."
            ))
    
    def _generate_strategy_tips(self):
        """투찰 전략 팁"""
        contract_type = self._contract_type()
        
        # 계약 유형별 기본 전략
        if contract_type == "CONSTRUCTION":
            self.tips.append(BidTip(
                category="strategy",
                icon="🎯",
                title="공사 입찰 투찰 전략",
                content=(
                    "공고의 낙찰자 결정 방식·적격심사 기준·A값·원가 조건을 함께 확인하세요. "
                    "가격 1순위와 최종 낙찰은 같은 결과가 아닙니다."
                ),
                source="안전 가이드",
                importance="MEDIUM",
                for_beginners=(
                    "확정 기초금액과 공고별 공식이 확인되기 전에는 추천가를 만들지 않습니다."
                ),
            ))
        elif contract_type == "SERVICE":
            self.tips.append(BidTip(
                category="strategy",
                icon="🎯",
                title="용역 입찰 투찰 전략",
                content="용역 입찰은 적격심사 방식이 많습니다.\n• 가격점수와 기술능력점수의 합계로 낙찰자가 결정됩니다.\n• 무조건 최저가가 유리한 것은 아닙니다.",
                source="법률 기반 + 일반 가이드",
                importance="MEDIUM"
            ))

    def _generate_personalization_tips(self):
        """사용자 맞춤형 팁 (지역/면허 매칭)"""
        if not self.user_profile:
            # 프로필이 없으면 안내 팁 추가 (Optional)
            return

        user_loc = self.user_profile.get("location")
        user_licenses = self.user_profile.get("licenses") # String containing licenses

        # 1. 지역 제한 체크
        bid_region = self.data.get("region")
        if bid_region and user_loc:
            # 단순 포함 관계 확인 (e.g. "경기" in "경기도")
            if (bid_region not in user_loc) and (user_loc not in bid_region):
                # 전국 공고인지 확인 (지역제한 없음)
                if bid_region != "전국": 
                    self.tips.insert(0, BidTip(
                        category="eligibility",
                        icon="❌",
                        title="지역 제한 불일치",
                        content=f"공고 지역은 '{bid_region}'이나, 귀사 소재지는 '{user_loc}'입니다. 투찰이 불가능할 수 있습니다.",
                        source="내 프로필 맞춤 분석",
                        importance="HIGH"
                    ))
            else:
                 self.tips.append(BidTip(
                    category="eligibility",
                    icon="✅",
                    title="지역 조건 충족",
                    content=f"귀사 소재지('{user_loc}')는 입찰 가능 지역입니다.",
                    source="내 프로필 맞춤 분석",
                    importance="LOW"
                ))

        # 2. 면허/업종 체크 (Simple Keyword Match)
        # 공고 제목이나 자격요건에서 업종 키워드 추출
        # 예: "전기", "통신", "소방", "토목", "건축"
        keywords_map = {
            "전기": "전기공사업",
            "통신": "정보통신공사업",
            "소방": "소방시설공사업",
            "토목": "토목공사업",
            "건축": "건축공사업",
            "실내": "실내건축공사업"
        }
        
        title = self.data.get("title", "")
        required_license = None
        for key, lic in keywords_map.items():
            if key in title:
                required_license = lic
                break
        
        if required_license and user_licenses:
            if required_license not in user_licenses:
                 self.tips.insert(0, BidTip(
                    category="eligibility",
                    icon="⚠️",
                    title="면허 확인 필요",
                    content=f"이 공고는 '{required_license}' 면허가 필요할 수 있습니다. 귀사 면허 보유 여부를 확인하세요.",
                    source="내 프로필 맞춤 분석",
                    importance="HIGH"
                ))


def generate_tips(bid_data: Dict[str, Any], user_profile: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    메인 함수: 입찰 데이터로부터 전략 팁 생성
    
    Returns:
        Dict containing summary, eligibility, tips, deadline_info, price_info
    """
    generator = TipsGenerator(bid_data, user_profile)
    return generator.generate_all_tips()
