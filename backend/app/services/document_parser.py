# -*- coding: utf-8 -*-
"""
Document Parser Service - Extracts text from HWP, HWPX, PDF files
For deep analysis of bid attachments
"""
import os
import re
import zlib
import struct
import zipfile
import xml.etree.ElementTree as ET
from typing import Optional

try:
    import olefile
    HAS_OLEFILE = True
except ImportError:
    HAS_OLEFILE = False
    print("[DocumentParser] Warning: olefile not installed. HWP parsing disabled.")


class HwpTextExtractor:
    """
    HWP 5.0 파일에서 텍스트 추출

    HWP 5.0은 OLE Compound File 구조를 사용
    - BodyText/Section0, Section1, ... 에 본문 텍스트 저장
    - 각 섹션은 zlib 압축되어 있음
    - 한글 문자열은 UTF-16LE 인코딩
    """

    # HWP 레코드 타입 상수
    HWPTAG_PARA_TEXT = 67  # 문단 텍스트 태그

    @staticmethod
    def extract(file_path: str) -> str:
        """
        HWP 파일에서 텍스트 추출

        Args:
            file_path: HWP 파일 경로

        Returns:
            추출된 텍스트 (실패시 빈 문자열)
        """
        if not HAS_OLEFILE:
            print("[HWP] olefile 라이브러리가 설치되지 않았습니다.")
            return ""

        if not os.path.exists(file_path):
            print(f"[HWP] 파일을 찾을 수 없음: {file_path}")
            return ""

        try:
            ole = olefile.OleFileIO(file_path)
        except Exception as e:
            print(f"[HWP] OLE 파일 열기 실패: {e}")
            return ""

        try:
            # FileHeader에서 압축 여부 확인
            is_compressed = HwpTextExtractor._check_compression(ole)

            # BodyText/Section* 스트림 수집
            sections = []
            for entry in ole.listdir():
                if entry[0] == "BodyText" and entry[1].startswith("Section"):
                    sections.append(entry)

            # 섹션 번호순 정렬
            sections.sort(key=lambda x: int(x[1].replace("Section", "")))

            all_text = []
            for section in sections:
                section_path = "/".join(section)
                try:
                    stream_data = ole.openstream(section_path).read()

                    # 압축 해제
                    if is_compressed:
                        try:
                            stream_data = zlib.decompress(stream_data, -15)
                        except zlib.error:
                            # 압축 안된 경우 그대로 사용
                            pass

                    # 레코드 파싱하여 텍스트 추출
                    text = HwpTextExtractor._parse_section_text(stream_data)
                    if text:
                        all_text.append(text)

                except Exception as e:
                    print(f"[HWP] 섹션 읽기 실패 {section_path}: {e}")
                    continue

            ole.close()
            return "\n".join(all_text)

        except Exception as e:
            print(f"[HWP] 텍스트 추출 실패: {e}")
            ole.close()
            return ""

    @staticmethod
    def _check_compression(ole) -> bool:
        """FileHeader에서 압축 여부 확인"""
        try:
            header = ole.openstream("FileHeader").read()
            # FileHeader의 36번째 바이트에 압축 플래그
            if len(header) > 36:
                flags = struct.unpack("<I", header[36:40])[0]
                return bool(flags & 0x01)  # 비트 0이 압축 여부
        except Exception:
            pass
        return True  # 기본값: 압축됨

    @staticmethod
    def _parse_section_text(data: bytes) -> str:
        """
        HWP 레코드 구조에서 텍스트 추출

        레코드 헤더: 4바이트
        - bits 0-9: 태그 ID
        - bits 10-19: 레벨
        - bits 20-31: 크기 (0x0fff면 다음 4바이트가 실제 크기)
        """
        texts = []
        pos = 0
        data_len = len(data)

        while pos < data_len - 4:
            try:
                # 레코드 헤더 읽기
                header = struct.unpack("<I", data[pos:pos+4])[0]
                tag_id = header & 0x3ff
                size = (header >> 20) & 0xfff
                pos += 4

                # 확장 크기 처리
                if size == 0xfff:
                    if pos + 4 > data_len:
                        break
                    size = struct.unpack("<I", data[pos:pos+4])[0]
                    pos += 4

                if pos + size > data_len:
                    break

                record_data = data[pos:pos+size]
                pos += size

                # HWPTAG_PARA_TEXT (67)에서 텍스트 추출
                if tag_id == HwpTextExtractor.HWPTAG_PARA_TEXT:
                    text = HwpTextExtractor._extract_para_text(record_data)
                    if text:
                        texts.append(text)

            except Exception:
                pos += 1  # 파싱 오류시 1바이트씩 이동
                continue

        return "".join(texts)

    @staticmethod
    def _extract_para_text(data: bytes) -> str:
        """
        PARA_TEXT 레코드에서 텍스트 추출
        UTF-16LE 인코딩, 제어 문자 필터링
        """
        text_chars = []
        i = 0
        data_len = len(data)

        while i < data_len - 1:
            char_code = struct.unpack("<H", data[i:i+2])[0]
            i += 2

            # HWP 제어 문자 처리
            if char_code < 32:
                # 특수 제어 문자 스킵
                skip_sizes = {
                    0: 0, 1: 0, 2: 0, 3: 0,  # 예약
                    4: 0, 5: 0, 6: 0, 7: 0,
                    8: 0,  # 섹션 정의
                    9: 0,  # 탭
                    10: 0, # 줄바꿈
                    11: 14, 12: 14, 13: 0,  # 각종 제어 문자
                    14: 0, 15: 14, 16: 14, 17: 14, 18: 14,
                    19: 14, 20: 14, 21: 14, 22: 14, 23: 14,
                    24: 0, 25: 0, 26: 0, 27: 0, 28: 0, 29: 0, 30: 0, 31: 0
                }
                skip = skip_sizes.get(char_code, 0)
                i += skip

                if char_code == 10:  # 줄바꿈
                    text_chars.append("\n")
                elif char_code == 9:  # 탭
                    text_chars.append(" ")
            else:
                # 일반 문자
                try:
                    text_chars.append(chr(char_code))
                except ValueError:
                    pass

        return "".join(text_chars)


class HwpxTextExtractor:
    """
    HWPX (한글 2014+) 파일에서 텍스트 추출

    HWPX는 ZIP 기반 XML 포맷 (OOXML과 유사)
    - Contents/section*.xml 에 본문 텍스트 저장
    - 텍스트는 <hp:t> 태그 내부에 저장
    """

    # HWPX XML 네임스페이스
    NAMESPACES = {
        'hp': 'http://www.hancom.co.kr/hwpml/2011/paragraph',
        'hc': 'http://www.hancom.co.kr/hwpml/2011/core',
    }

    @staticmethod
    def extract(file_path: str) -> str:
        """
        HWPX 파일에서 텍스트 추출

        Args:
            file_path: HWPX 파일 경로

        Returns:
            추출된 텍스트 (실패시 빈 문자열)
        """
        if not os.path.exists(file_path):
            print(f"[HWPX] 파일을 찾을 수 없음: {file_path}")
            return ""

        try:
            with zipfile.ZipFile(file_path, 'r') as zf:
                # Contents/section*.xml 파일 목록 수집
                section_files = []
                for name in zf.namelist():
                    if name.startswith('Contents/section') and name.endswith('.xml'):
                        section_files.append(name)

                if not section_files:
                    print(f"[HWPX] 섹션 파일을 찾을 수 없음: {file_path}")
                    return ""

                # 섹션 번호순 정렬 (section0.xml, section1.xml, ...)
                section_files.sort(key=lambda x: int(re.search(r'section(\d+)', x).group(1)))

                all_text = []
                for section_file in section_files:
                    try:
                        xml_content = zf.read(section_file)
                        text = HwpxTextExtractor._parse_section_xml(xml_content)
                        if text:
                            all_text.append(text)
                    except Exception as e:
                        print(f"[HWPX] 섹션 파싱 실패 {section_file}: {e}")
                        continue

                return "\n".join(all_text)

        except zipfile.BadZipFile:
            print(f"[HWPX] 잘못된 ZIP 파일: {file_path}")
            return ""
        except Exception as e:
            print(f"[HWPX] 텍스트 추출 실패: {e}")
            return ""

    @staticmethod
    def _parse_section_xml(xml_content: bytes) -> str:
        """
        섹션 XML에서 텍스트 추출

        Args:
            xml_content: XML 파일 내용

        Returns:
            추출된 텍스트
        """
        try:
            root = ET.fromstring(xml_content)
        except ET.ParseError as e:
            print(f"[HWPX] XML 파싱 오류: {e}")
            return ""

        texts = []

        # <hp:t> 태그에서 텍스트 추출 (네임스페이스 사용)
        for t_elem in root.iter('{http://www.hancom.co.kr/hwpml/2011/paragraph}t'):
            if t_elem.text:
                texts.append(t_elem.text)

        # 네임스페이스 없이도 시도 (일부 HWPX 파일 호환)
        if not texts:
            for t_elem in root.iter():
                if t_elem.tag.endswith('}t') or t_elem.tag == 't':
                    if t_elem.text:
                        texts.append(t_elem.text)

        # 문단 구분을 위해 줄바꿈 추가
        return "\n".join(texts)


class PdfTextExtractor:
    """
    PDF 파일에서 텍스트 추출
    PyMuPDF(fitz) 사용
    """

    @staticmethod
    def extract(file_path: str) -> str:
        """
        PDF 파일에서 텍스트 추출

        Args:
            file_path: PDF 파일 경로

        Returns:
            추출된 텍스트 (실패시 빈 문자열)
        """
        try:
            import fitz  # PyMuPDF
        except ImportError:
            print("[PDF] PyMuPDF(fitz) 라이브러리가 설치되지 않았습니다.")
            return ""

        if not os.path.exists(file_path):
            print(f"[PDF] 파일을 찾을 수 없음: {file_path}")
            return ""

        try:
            doc = fitz.open(file_path)
            text_parts = []

            for page_num in range(len(doc)):
                page = doc.load_page(page_num)
                text = page.get_text()
                if text:
                    text_parts.append(text)

            doc.close()
            return "\n".join(text_parts)

        except Exception as e:
            print(f"[PDF] 텍스트 추출 실패: {e}")
            return ""


class DocumentParser:
    """
    통합 문서 파서
    파일 확장자에 따라 적절한 파서 선택
    """

    SUPPORTED_EXTENSIONS = {".hwp", ".hwpx", ".pdf"}

    @staticmethod
    def extract_text(file_path: str) -> Optional[str]:
        """
        파일에서 텍스트 추출

        Args:
            file_path: 문서 파일 경로

        Returns:
            추출된 텍스트 (지원하지 않는 형식이면 None)
        """
        ext = os.path.splitext(file_path)[1].lower()

        if ext == ".hwp":
            return HwpTextExtractor.extract(file_path)
        elif ext == ".hwpx":
            return HwpxTextExtractor.extract(file_path)
        elif ext == ".pdf":
            return PdfTextExtractor.extract(file_path)
        else:
            print(f"[DocumentParser] 지원하지 않는 파일 형식: {ext}")
            return None

    @staticmethod
    def is_supported(file_path: str) -> bool:
        """파일 형식 지원 여부 확인"""
        ext = os.path.splitext(file_path)[1].lower()
        return ext in DocumentParser.SUPPORTED_EXTENSIONS
