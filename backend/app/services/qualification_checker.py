"""
자격 자동 판정 + 처방 (입찰 안전망 레이어 ③ — 자격탈락 방지)
==============================================================
판정(PASS/FAIL/UNKNOWN)에 그치지 않고, FAIL 이면 "무엇이 안 맞고 어떻게 하면
참여할 수 있는지" 처방까지 제시한다 (2026-07-18, docs/COMPETITIVE_STRATEGY.md §2-③).

정직 원칙:
- **데이터가 있는 요건만 처방한다.** 지역(공고 region)·면허(공고명 키워드 추정)만.
  실적·시공능력 기준액은 공고 데이터에 없으므로 처방하지 않는다(지어내기 금지).
- 면허 요건은 공고명 키워드 **추정**임을 처방 문구에 명시한다.
- 프로필 미기재는 "자격 미달(FAIL)"이 아니라 "판정 불가(UNKNOWN)" — 정보 부족을
  탈락으로 단정하지 않는다.

하위 호환:
- 반환의 status/message/details 는 기존 그대로 (details: PASS=뱃지, FAIL=사유 문자열).
- prescriptions 는 **추가 필드** — 기존 5개 호출처(bids/ai/prediction/recommend/leads)는
  무시해도 동작 불변.
"""
from typing import Dict, List

from app.db import models


class QualificationChecker:
    """
    Analyzes if a user is qualified for a specific bid notice.
    Checks:
    1. Location (Region)
    2. Licenses (Qualification)
    3. Performance/Capacity — 공고 측 기준액 데이터가 없어 미판정(처방도 안 함)
    """

    # 공고명 키워드 → 정식 면허명 (제목 기반 추정)
    LICENSE_KEYWORDS = {
        "전기": "전기공사업",
        "통신": "정보통신공사업",
        "소방": "소방시설공사업",
        "건축": "건축공사업",
        "토목": "토목공사업",
    }

    @staticmethod
    def check_qualification(notice: Dict, user: models.User) -> Dict:
        """
        Returns:
        {
            "status": "PASS" | "FAIL" | "UNKNOWN",
            "message": str,
            "details": List[str],   # PASS=뱃지 / 그 외=사유 (기존 호환)
            "prescriptions": List[{"requirement","issue","action","confidence"}]
        }
        """
        reasons: List[str] = []
        badges: List[str] = []
        prescriptions: List[Dict] = []
        has_hard_fail = False      # 확정 미달 (지역 불일치·면허 미보유)
        has_missing_info = False   # 프로필 미기재 (판정 불가)

        # 1. Location Check
        bid_region = notice.get("LmtRegion", "")
        user_location = user.location or ""

        if bid_region and "전국" not in bid_region:
            if not user_location:
                has_missing_info = True
                reasons.append("사업장 소재지 정보가 없습니다.")
                prescriptions.append({
                    "requirement": "프로필",
                    "issue": "사업장 소재지가 등록돼 있지 않아요.",
                    "action": "프로필에서 소재지를 등록하면 공고마다 지역 제한을 자동 판정해드려요.",
                    "confidence": "확정",
                })
            elif user_location[:2] not in bid_region:
                has_hard_fail = True
                reasons.append(f"지역 제한 불일치 (공고: {bid_region} vs 나: {user_location})")
                prescriptions.append({
                    "requirement": "지역",
                    "issue": f"이 공고는 {bid_region} 소재 업체로 제한돼 있어요 (내 사업장: {user_location}).",
                    "action": (
                        "공고 지역에 주된 영업소(본사)가 있어야 참여할 수 있어요. "
                        "해당 지역 업체와의 공동수급(컨소시엄) 허용 여부를 공고문에서 확인해 보세요."
                    ),
                    "confidence": "확정",
                })
            else:
                badges.append("지역적합")
        else:
            badges.append("지역제한없음")

        # 2. License Check — 공고명 키워드 기반 추정
        bid_title = notice.get("bidNtceNm", "")
        user_licenses = user.licenses or ""

        required_keys = [k for k in QualificationChecker.LICENSE_KEYWORDS if k in bid_title]

        if required_keys:
            if not user_licenses:
                has_missing_info = True
                reasons.append("등록된 면허 정보가 없습니다.")
                prescriptions.append({
                    "requirement": "프로필",
                    "issue": "보유 면허가 등록돼 있지 않아요.",
                    "action": "프로필에서 보유 면허를 등록하면 필요 면허 충족 여부를 자동 판정해드려요.",
                    "confidence": "확정",
                })
            else:
                has_license = any(req in user_licenses for req in required_keys)
                if not has_license:
                    has_hard_fail = True
                    req_str = ", ".join(required_keys)
                    full_names = ", ".join(
                        QualificationChecker.LICENSE_KEYWORDS[k] for k in required_keys
                    )
                    reasons.append(f"필수 면허 미보유 (필요: {req_str} 관련)")
                    prescriptions.append({
                        "requirement": "면허",
                        "issue": f"공고명 기준으로 {full_names} 등록이 필요해 보여요.",
                        "action": (
                            "해당 업종을 등록하거나, 보유 업체와의 공동수급을 검토해 보세요. "
                            "정확한 요건은 공고문·첨부의 입찰참가자격을 꼭 확인하세요."
                        ),
                        "confidence": "추정",
                    })
                else:
                    badges.append("면허보유")

        # Result Logic — 확정 미달이 하나라도 있으면 FAIL,
        # 미달 없이 미기재만 있으면 UNKNOWN(판정 불가), 그 외 PASS.
        if has_hard_fail:
            return {
                "status": "FAIL",
                "message": "입찰 자격 요건을 만족하지 않습니다.",
                "details": reasons,
                "prescriptions": prescriptions,
            }
        if has_missing_info:
            return {
                "status": "UNKNOWN",
                "message": "프로필 정보가 부족해 자격을 판정할 수 없어요.",
                "details": reasons,
                "prescriptions": prescriptions,
            }
        return {
            "status": "PASS",
            "message": "입찰 참여가 가능합니다.",
            "details": badges,
            "prescriptions": [],
        }
