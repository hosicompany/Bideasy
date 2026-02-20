# -*- coding: utf-8 -*-
"""
Document Parser Test Script
관공서 문서 형식 파싱 테스트
"""
import os
import sys

# 프로젝트 경로 추가
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.services.document_parser import DocumentParser

def test_library_imports():
    """라이브러리 임포트 테스트"""
    print("=" * 50)
    print("[1] 라이브러리 임포트 테스트")
    print("=" * 50)
    
    results = {}
    
    # olefile (HWP)
    try:
        import olefile
        results['olefile (HWP)'] = f"OK - v{olefile.__version__ if hasattr(olefile, '__version__') else 'installed'}"
    except ImportError as e:
        results['olefile (HWP)'] = f"FAIL - {e}"
    
    # PyMuPDF (PDF)
    try:
        import fitz
        results['PyMuPDF (PDF)'] = f"OK - v{fitz.version[0]}"
    except ImportError as e:
        results['PyMuPDF (PDF)'] = f"FAIL - {e}"
    
    # openpyxl (Excel)
    try:
        import openpyxl
        results['openpyxl (Excel)'] = f"OK - v{openpyxl.__version__}"
    except ImportError as e:
        results['openpyxl (Excel)'] = f"FAIL - {e}"
    
    # python-docx (Word)
    try:
        from docx import Document  # noqa: F401
        results['python-docx (Word)'] = "OK"
    except ImportError as e:
        results['python-docx (Word)'] = f"FAIL - {e}"
    
    for lib, status in results.items():
        print(f"  {lib}: {status}")
    
    return all('OK' in str(v) for v in results.values())


def test_hwp_sample():
    """HWP 파일 테스트 - 나라장터 샘플 다운로드"""
    print("\n" + "=" * 50)
    print("[2] HWP 파일 파싱 테스트")
    print("=" * 50)
    
    # 공개된 HWP 샘플 URL (정부24 양식 등)
    
    # 로컬 HWP 파일 찾기
    local_hwp_files = []
    search_paths = [
        os.path.expanduser("~/Documents"),
        os.path.expanduser("~/Downloads"),
        "C:/Users/hosic/OneDrive/Coding/MyProject/01_Bid Easy",
    ]
    
    for search_path in search_paths:
        if os.path.exists(search_path):
            for root, dirs, files in os.walk(search_path):
                for f in files:
                    if f.endswith('.hwp') or f.endswith('.hwpx'):
                        local_hwp_files.append(os.path.join(root, f))
                        if len(local_hwp_files) >= 3:
                            break
                if len(local_hwp_files) >= 3:
                    break
        if len(local_hwp_files) >= 3:
            break
    
    if local_hwp_files:
        print(f"\n  로컬 HWP 파일 발견: {len(local_hwp_files)}개")
        for hwp_path in local_hwp_files[:3]:
            print(f"\n  테스트 파일: {os.path.basename(hwp_path)}")
            try:
                text = DocumentParser.extract_text(hwp_path)
                if text:
                    preview = text[:300].replace('\n', ' ')
                    print("  [성공] 추출된 텍스트 (미리보기):")
                    print(f"    {preview}...")
                    print(f"  [성공] 총 {len(text)} 글자 추출")
                    return True
                else:
                    print("  [실패] 텍스트 추출 실패 (빈 결과)")
            except Exception as e:
                print(f"  [오류] {e}")
    else:
        print("  로컬 HWP 파일을 찾을 수 없습니다.")
        print("  HWP 테스트 파일을 다운로드 폴더에 넣어주세요.")
    
    return False


def test_pdf_sample():
    """PDF 파일 테스트"""
    print("\n" + "=" * 50)
    print("[3] PDF 파일 파싱 테스트")
    print("=" * 50)
    
    # 로컬 PDF 파일 찾기
    local_pdf_files = []
    search_paths = [
        os.path.expanduser("~/Documents"),
        os.path.expanduser("~/Downloads"),
    ]
    
    for search_path in search_paths:
        if os.path.exists(search_path):
            for root, dirs, files in os.walk(search_path):
                for f in files:
                    if f.endswith('.pdf'):
                        local_pdf_files.append(os.path.join(root, f))
                        if len(local_pdf_files) >= 1:
                            break
                if len(local_pdf_files) >= 1:
                    break
        if len(local_pdf_files) >= 1:
            break
    
    if local_pdf_files:
        pdf_path = local_pdf_files[0]
        print(f"\n  테스트 파일: {os.path.basename(pdf_path)}")
        try:
            text = DocumentParser.extract_text(pdf_path)
            if text:
                preview = text[:300].replace('\n', ' ')
                print("  [성공] 추출된 텍스트 (미리보기):")
                print(f"    {preview}...")
                print(f"  [성공] 총 {len(text)} 글자 추출")
                return True
            else:
                print("  [실패] 텍스트 추출 실패")
        except Exception as e:
            print(f"  [오류] {e}")
    else:
        print("  로컬 PDF 파일을 찾을 수 없습니다.")
    
    return False


def test_supported_formats():
    """지원 형식 확인"""
    print("\n" + "=" * 50)
    print("[4] 지원 문서 형식")
    print("=" * 50)
    
    formats = DocumentParser.get_supported_formats()
    for fmt in formats:
        print(f"  {fmt['ext']:8} - {fmt['name']:15} (라이브러리: {fmt['lib']})")
    
    return True


if __name__ == "__main__":
    print("\n" + "=" * 50)
    print("  BidEasy 문서 파서 테스트")
    print("=" * 50)
    
    results = {
        "라이브러리 임포트": test_library_imports(),
        "HWP 파싱": test_hwp_sample(),
        "PDF 파싱": test_pdf_sample(),
        "지원 형식": test_supported_formats(),
    }
    
    print("\n" + "=" * 50)
    print("  테스트 결과 요약")
    print("=" * 50)
    for name, passed in results.items():
        status = "PASS" if passed else "FAIL"
        print(f"  {name}: {status}")
    
    print("\n")
