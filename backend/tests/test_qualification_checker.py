"""
자격 판정 + 처방 엔진 테스트 (2026-07-18 · 안전망 레이어 ③)
=============================================================
기존엔 checker 전용 테스트가 없었다(간접 커버만). 판정 정오 + 처방 내용 +
하위 호환(details 문자열·뱃지 의미)을 직접 고정한다.
"""
from types import SimpleNamespace

from app.services.qualification_checker import QualificationChecker


def _user(location=None, licenses=None):
    return SimpleNamespace(location=location, licenses=licenses)


def _notice(title="테스트 공고", region=""):
    return {"bidNtceNm": title, "LmtRegion": region, "bidNtceNo": "T-1"}


class TestPass:
    def test_full_pass_badges_and_empty_prescriptions(self):
        q = QualificationChecker.check_qualification(
            _notice("부산 A초교 전기공사", "부산광역시"),
            _user(location="부산광역시", licenses="전기공사업"),
        )
        assert q["status"] == "PASS"
        assert "지역적합" in q["details"]
        assert "면허보유" in q["details"]
        assert q["prescriptions"] == []

    def test_nationwide_no_region_limit_badge(self):
        q = QualificationChecker.check_qualification(
            _notice("전국 물품 구매", ""), _user(location=None, licenses=None)
        )
        assert q["status"] == "PASS"
        assert "지역제한없음" in q["details"]


class TestFailWithPrescription:
    def test_region_mismatch_prescribes_action(self):
        q = QualificationChecker.check_qualification(
            _notice("서울 D청사 전기공사", "서울특별시"),
            _user(location="부산광역시", licenses="전기공사업"),
        )
        assert q["status"] == "FAIL"
        # 기존 사유 문자열 완전 호환
        assert any("지역 제한 불일치" in d for d in q["details"])
        # 처방: 지역 요건, 공동수급 안내, 확정 신뢰도
        rx = [p for p in q["prescriptions"] if p["requirement"] == "지역"]
        assert len(rx) == 1
        assert "공동수급" in rx[0]["action"]
        assert rx[0]["confidence"] == "확정"

    def test_license_missing_prescribes_full_name_as_estimate(self):
        q = QualificationChecker.check_qualification(
            _notice("부산 E센터 정보통신공사", "부산광역시"),
            _user(location="부산광역시", licenses="전기공사업"),
        )
        assert q["status"] == "FAIL"
        assert any("필수 면허 미보유" in d for d in q["details"])
        rx = [p for p in q["prescriptions"] if p["requirement"] == "면허"]
        assert len(rx) == 1
        # 정식 면허명 + 추정 명시 (공고명 기반이므로)
        assert "정보통신공사업" in rx[0]["issue"]
        assert rx[0]["confidence"] == "추정"
        assert "공고문" in rx[0]["action"]  # 원문 확인 안내 (정직)

    def test_hard_fail_wins_over_missing_info(self):
        """지역 확정 불일치 + 면허 미기재 → FAIL (미기재가 있어도 확정 미달 우선)."""
        q = QualificationChecker.check_qualification(
            _notice("서울 전기공사", "서울특별시"),
            _user(location="부산광역시", licenses=None),
        )
        assert q["status"] == "FAIL"
        reqs = {p["requirement"] for p in q["prescriptions"]}
        assert "지역" in reqs and "프로필" in reqs


class TestUnknownForMissingProfile:
    def test_no_location_is_unknown_not_fail(self):
        """소재지 미기재 = 판정 불가(UNKNOWN) — 자격 미달로 단정하지 않는다."""
        q = QualificationChecker.check_qualification(
            _notice("서울 전기공사", "서울특별시"),
            _user(location=None, licenses="전기공사업"),
        )
        assert q["status"] == "UNKNOWN"
        assert any("소재지 정보가 없습니다" in d for d in q["details"])
        rx = q["prescriptions"]
        assert rx and rx[0]["requirement"] == "프로필"
        assert "프로필" in rx[0]["action"]

    def test_no_licenses_is_unknown(self):
        q = QualificationChecker.check_qualification(
            _notice("부산 정보통신공사", "부산광역시"),
            _user(location="부산광역시", licenses=None),
        )
        assert q["status"] == "UNKNOWN"
        assert any("면허 정보가 없습니다" in d for d in q["details"])


class TestBackwardCompat:
    def test_details_are_plain_strings(self):
        """details 는 문자열 리스트 유지 — 5개 호출처(ai tip details[0] 등) 호환."""
        q = QualificationChecker.check_qualification(
            _notice("서울 전기공사", "서울특별시"),
            _user(location="부산광역시", licenses="전기공사업"),
        )
        assert all(isinstance(d, str) for d in q["details"])

    def test_pass_details_contain_recommend_badges(self):
        """recommendation_tasks 가 요구하는 긍정 뱃지({지역적합, 면허보유}) 유지."""
        q = QualificationChecker.check_qualification(
            _notice("부산 전기공사", "부산광역시"),
            _user(location="부산광역시", licenses="전기공사업"),
        )
        assert {"지역적합", "면허보유"} & set(q["details"])
