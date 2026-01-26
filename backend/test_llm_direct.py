# -*- coding: utf-8 -*-
"""Test LLM Agent directly to see error"""
from app.services.llm_agent import llm_agent

test_input = """
=== 공고 기본 정보 ===
공고명: 부산광역시 기장군 청사 리모델링 공사
공고기관: 부산광역시 기장군
수요기관: 기장군청
공고상태: 일반공고

=== 금액 정보 ===
기초금액: 830,990,000원
배정예산: 900,000,000원

=== 입찰 방식 ===
입찰방법: 전자입찰
계약방법: 일반경쟁입찰
입찰분류: 공사

=== 참가 자격 ===
참가제한지역: 부산광역시
중소기업 제한: 예 (중소기업만 참가 가능)
공동계약 가능: 예

=== 일정 ===
입찰시작: 2026-01-25T09:00:00
입찰마감: 2026-01-29T18:00:00
개찰일시: 2026-01-30 14:00
"""

print("Testing LLM Agent...")
try:
    result = llm_agent.analyze_notice(test_input)
    print("SUCCESS!")
    print(f"Badges: {result.get('badges', [])}")
    print(f"Check Items: {len(result.get('check_items', []))} items")
    for item in result.get('check_items', []):
        print(f"  - [{item.get('status')}] {item.get('label')}: {item.get('text')}")
    print(f"Tips: {result.get('tips', [])}")
except Exception as e:
    print(f"ERROR: {type(e).__name__}: {e}")
