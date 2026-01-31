# -*- coding: utf-8 -*-
"""Test Document Parser and AI Analyzer directly"""
import os
import sys

# Test 1: Document Parser Import
print("=" * 50)
print("Test 1: Document Parser Import")
print("=" * 50)
try:
    from app.services.document_parser import DocumentParser, HwpTextExtractor, PdfTextExtractor
    print("[OK] DocumentParser imported successfully")
    print(f"  Supported formats: {DocumentParser.SUPPORTED_EXTENSIONS}")
except Exception as e:
    print(f"[FAIL] Import failed: {e}")
    sys.exit(1)

# Test 2: AI Analyzer Import
print("\n" + "=" * 50)
print("Test 2: AI Analyzer Import")
print("=" * 50)
try:
    from app.services.ai_analyzer import DocumentAnalyzer, document_analyzer
    print("[OK] DocumentAnalyzer imported successfully")
    print(f"  Model: {document_analyzer.model}")
    print(f"  Fallback: {document_analyzer.fallback_model}")
except Exception as e:
    print(f"[FAIL] Import failed: {e}")

# Test 3: Schema Import
print("\n" + "=" * 50)
print("Test 3: Analysis Schema Import")
print("=" * 50)
try:
    from app.schemas.analysis import DeepAnalysisResponse, ToxicClause, QualificationRequirement
    print("[OK] Analysis schemas imported successfully")

    # Test schema creation
    sample = DeepAnalysisResponse(
        bid_id="TEST001",
        bid_title="Test Notice",
        qualification_requirements=[
            {"category": "License", "content": "Construction License", "importance": "Required"}
        ],
        toxic_clauses=[
            {"type": "Penalty", "content": "3/1000 per day", "severity": "HIGH"}
        ],
        key_conditions=[
            {"category": "Duration", "content": "180 days"}
        ],
        risk_assessment="MEDIUM",
        summary="Test summary.",
        analyzed_files=["test.hwp"]
    )
    print(f"  Sample response created: bid_id={sample.bid_id}")
except Exception as e:
    print(f"[FAIL] Schema test failed: {e}")

# Test 4: AI Analyzer with sample text (requires API key)
print("\n" + "=" * 50)
print("Test 4: AI Analysis (Sample Text)")
print("=" * 50)

sample_document = """
Chapter 1 General Provisions
Article 1 (Purpose) This contract defines matters regarding construction between the client and contractor.

Chapter 2 Qualification Requirements
Article 5 (Eligibility)
1. Must hold a construction business license
2. Similar construction experience of at least 1 billion KRW in the last 3 years
3. Company headquartered in Seoul

Chapter 3 Contract Conditions
Article 10 (Construction Period) Complete within 90 days from commencement
Article 11 (Delay Penalty) 3/1000 of contract amount per day of delay
Article 12 (Warranty) 5-year defect repair obligation after completion

Chapter 4 Payment Terms
Article 15 (Progress Payment) Paid within 14 days after monthly inspection
Article 16 (Final Payment) Paid within 30 days after completion inspection
"""

try:
    print("Analyzing sample document...")
    result = document_analyzer.analyze_attachment(sample_document, {"title": "Test Construction"})

    if "error" in result and result["error"]:
        print(f"  Analysis error: {result['error']}")
    else:
        print("[OK] Analysis completed successfully!")
        print(f"  Risk Assessment: {result.get('risk_assessment', 'N/A')}")
        print(f"  Qualifications: {len(result.get('qualification_requirements', []))} items")
        print(f"  Toxic Clauses: {len(result.get('toxic_clauses', []))} items")
        print(f"  Key Conditions: {len(result.get('key_conditions', []))} items")

        summary = result.get('summary', 'N/A')
        if summary:
            print(f"  Summary: {summary[:100]}...")

        if result.get('toxic_clauses'):
            print("\n  Toxic Clauses Found:")
            for tc in result['toxic_clauses'][:3]:
                content = tc.get('content', '')[:50]
                print(f"    - [{tc.get('severity')}] {tc.get('type')}: {content}")

except Exception as e:
    print(f"[FAIL] Analysis failed: {e}")

print("\n" + "=" * 50)
print("Test Complete!")
print("=" * 50)
