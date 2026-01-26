# -*- coding: utf-8 -*-
"""Test LLM with current settings"""
from app.services.llm_agent import llm_agent
import time

print(f"Current Model: {llm_agent.model}")

try:
    print("Sending request to LLM...")
    result = llm_agent.analyze_notice("테스트 공고입니다. 지역은 서울, 면허는 전기공사업입니다.")
    print("SUCCESS!")
    print(result)
except Exception as e:
    print("FAILED!")
    print(f"Error: {e}")
