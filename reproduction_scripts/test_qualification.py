import sys
import os

# Add backend directory to sys.path to import app modules
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../backend')))

from app.services.qualification_checker import QualificationChecker
from app.db import models

def test_qualification():
    print("🧪 Testing Qualification Logic...\n")

    # 1. Create Mock User (Busan, Electric)
    user = models.User(
        id=1,
        location="부산광역시",
        licenses="전기공사업"
    )
    print(f"👤 User Profile:")
    print(f"   - Location: {user.location}")
    print(f"   - Licenses: {user.licenses}\n")

    # 2. Test Case 1: FAIL (Region Mismatch)
    # Notice: Seoul, Electric
    notice_seoul = {
        "bidNtceNm": "서울 강남구 전기 공사",
        "LmtRegion": "서울특별시",
    }
    print(f"📋 Case 1: Seoul Notice (Region Mismatch)")
    print(f"   - Notice Region: {notice_seoul['LmtRegion']}")
    
    result_fail = QualificationChecker.check_qualification(notice_seoul, user)
    print(f"   👉 Result: {result_fail['status']}")
    print(f"   👉 Message: {result_fail['message']}")
    print(f"   👉 Reasons: {result_fail['details']}\n")

    # 3. Test Case 2: PASS (Region Match)
    # Notice: Busan, Electric
    notice_busan = {
        "bidNtceNm": "부산 해운대구 전기 공사",
        "LmtRegion": "부산광역시",
    }
    print(f"📋 Case 2: Busan Notice (Region Match)")
    print(f"   - Notice Region: {notice_busan['LmtRegion']}")
    
    result_pass = QualificationChecker.check_qualification(notice_busan, user)
    print(f"   👉 Result: {result_pass['status']}")
    print(f"   👉 Message: {result_pass['message']}")
    print(f"   👉 Details: {result_pass['details']}\n")

if __name__ == "__main__":
    test_qualification()
