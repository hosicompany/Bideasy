from typing import Dict, List, Optional
from app.db import models

class QualificationChecker:
    """
    Analyzes if a user is qualified for a specific bid notice.
    Checks:
    1. Location (Region)
    2. Licenses (Qualification)
    3. Performance/Capacity (Performance limit) - Optional implementation
    """

    @staticmethod
    def check_qualification(notice: Dict, user: models.User) -> Dict:
        """
        Returns:
        {
            "is_qualified": bool,
            "reasons": List[str], # Fail reasons or Pass details
            "badges": List[str]   # e.g. ["지역적합", "면허보유"]
        }
        """
        reasons = []
        badges = []
        is_qualified = True

        # 1. Location Check
        # Notice often has LmtRegion (e.g. "서울특별시")
        bid_region = notice.get("LmtRegion", "")
        user_location = user.location or ""
        
        # If bid has region limit and it's not empty/nationwide
        if bid_region and "전국" not in bid_region:
            # Simple substring match (e.g. "서울" in "서울특별시")
            if not user_location:
                 is_qualified = False
                 reasons.append("사업장 소재지 정보가 없습니다.")
            elif user_location[:2] not in bid_region: 
                # e.g. User "부산" not in Bid "서울"
                is_qualified = False
                reasons.append(f"지역 제한 불일치 (공고: {bid_region} vs 나: {user_location})")
            else:
                badges.append("지역적합")
        else:
            badges.append("지역제한없음")

        # 2. License Check
        # Notice 'sucsfbidMthdNm' or specific text usually contains keywords like "전기", "정보통신"
        # Since we rely on keywords for now (as structured code might be missing):
        bid_title = notice.get("bidNtceNm", "")
        user_licenses = user.licenses or ""
        
        # Define keywords for common licenses
        license_keywords = {
            "전기": "전기공사업",
            "통신": "정보통신공사업",
            "소방": "소방시설공사업",
            "건축": "건축공사업",
            "토목": "토목공사업"
        }
        
        required_licenses = []
        for key, full_name in license_keywords.items():
            if key in bid_title:
                required_licenses.append(key)
        
        if required_licenses:
            if not user_licenses:
                is_qualified = False
                reasons.append("등록된 면허 정보가 없습니다.")
            else:
                has_license = any(req in user_licenses for req in required_licenses)
                if not has_license:
                    is_qualified = False
                    req_str = ", ".join(required_licenses)
                    reasons.append(f"필수 면허 미보유 (필요: {req_str} 관련)")
                else:
                    badges.append("면허보유")

        # Result Logic
        if is_qualified:
            return {
                "status": "PASS",
                "message": "입찰 참여가 가능합니다.",
                "details": badges
            }
        else:
            return {
                "status": "FAIL",
                "message": "입찰 자격 요건을 만족하지 않습니다.",
                "details": reasons
            }
