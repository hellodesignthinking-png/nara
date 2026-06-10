"""
HWP 파일 텍스트 추출 모듈

olefile 라이브러리를 사용하여 HWP 파일의 OLE 구조에서
본문 텍스트를 추출합니다.

HWP 파일 구조:
  - FileHeader: 파일 헤더 정보
  - BodyText/Section0, Section1, ...: 본문 텍스트 (zlib 압축)
  - DocInfo: 문서 정보
"""

import logging
import re
import struct
import zlib
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# 보안 상수
MAX_FILE_SIZE = 100 * 1024 * 1024         # 100MB 파일 크기 제한
MAX_DECOMPRESSED_SIZE = 50 * 1024 * 1024  # 50MB 압축 해제 크기 제한


def extract_text(file_path: str) -> str:
    """
    HWP 파일에서 텍스트를 추출합니다.

    Args:
        file_path: HWP 파일 경로

    Returns:
        추출된 텍스트 문자열. 실패 시 빈 문자열 반환.
    """
    try:
        # olefile은 선택적 의존성이므로 런타임에 임포트
        import olefile
    except ImportError:
        logger.warning(
            "olefile 라이브러리가 설치되지 않았습니다. "
            "'pip install olefile'로 설치해 주세요."
        )
        return ""

    file_path = Path(file_path)
    if not file_path.exists():
        logger.warning("HWP 파일을 찾을 수 없습니다: %s", file_path)
        return ""

    # 파일 크기 제한 확인
    file_size = file_path.stat().st_size
    if file_size > MAX_FILE_SIZE:
        logger.warning(
            "HWP 파일이 너무 큽니다: %s (%d bytes, 최대: %d bytes)",
            file_path, file_size, MAX_FILE_SIZE,
        )
        return ""

    try:
        ole = olefile.OleFileIO(str(file_path))
    except Exception as e:
        logger.warning("HWP 파일을 열 수 없습니다: %s (오류: %s)", file_path, e)
        return ""

    try:
        # 파일 헤더에서 압축 여부 확인
        is_compressed = _check_compressed(ole)

        # 본문 섹션 스트림 목록 수집
        sections = _get_body_sections(ole)
        if not sections:
            logger.warning("HWP 파일에서 본문 섹션을 찾을 수 없습니다: %s", file_path)
            return ""

        # 각 섹션에서 텍스트 추출
        all_text = []
        for section_path in sections:
            text = _extract_section_text(ole, section_path, is_compressed)
            if text:
                all_text.append(text)

        # 최종 텍스트 정리
        result = "\n".join(all_text)
        result = _clean_text(result)

        logger.info(
            "HWP 텍스트 추출 완료: %s (길이: %d자)", file_path.name, len(result)
        )
        return result

    except Exception as e:
        logger.warning("HWP 텍스트 추출 중 오류 발생: %s (오류: %s)", file_path, e)
        return ""

    finally:
        ole.close()


def _check_compressed(ole) -> bool:
    """
    FileHeader 스트림에서 압축 플래그를 확인합니다.

    HWP 파일 헤더의 36번째 바이트 위치에 속성 플래그가 있으며,
    비트 0이 1이면 본문이 압축되어 있음을 나타냅니다.
    """
    try:
        header = ole.openstream("FileHeader")
        header_data = header.read()
        # 속성 플래그는 오프셋 36에 위치 (4바이트 리틀엔디안)
        if len(header_data) >= 40:
            flags = struct.unpack_from("<I", header_data, 36)[0]
            return bool(flags & 0x01)  # 비트 0: 압축 여부
    except Exception:
        pass
    # 기본값: 압축된 것으로 간주 (대부분의 HWP 파일이 압축됨)
    return True


def _get_body_sections(ole) -> list[str]:
    """
    OLE 스트림에서 BodyText/Section* 경로 목록을 추출합니다.

    Returns:
        정렬된 섹션 경로 리스트 (예: ['BodyText/Section0', 'BodyText/Section1'])
    """
    sections = []
    for stream in ole.listdir():
        # stream은 리스트 형태, 예: ['BodyText', 'Section0']
        path = "/".join(stream)
        if path.startswith("BodyText/Section"):
            sections.append(path)

    # 섹션 번호 기준 정렬
    def _section_sort_key(p: str) -> int:
        m = re.search(r"Section(\d+)", p)
        return int(m.group(1)) if m else 0

    sections.sort(key=_section_sort_key)
    return sections


def _extract_section_text(
    ole, section_path: str, is_compressed: bool
) -> Optional[str]:
    """
    단일 섹션 스트림에서 텍스트를 추출합니다.

    Args:
        ole: OleFileIO 객체
        section_path: 섹션 스트림 경로
        is_compressed: 압축 여부

    Returns:
        추출된 텍스트 또는 None
    """
    try:
        stream = ole.openstream(section_path)
        data = stream.read()

        # 압축 해제
        if is_compressed:
            try:
                data = zlib.decompress(data, -15)
            except zlib.error:
                # wbits=-15 실패 시 기본값으로 재시도
                try:
                    data = zlib.decompress(data)
                except zlib.error:
                    logger.debug("섹션 압축 해제 실패: %s", section_path)
                    return None

            # 압축 해제 크기 제한 (decompression bomb 방지)
            if len(data) > MAX_DECOMPRESSED_SIZE:
                logger.warning("압축 해제 크기 제한 초과: %d bytes", len(data))
                return ""

        # 바이너리 레코드에서 텍스트 추출
        text = _parse_hwp_text_records(data)
        return text

    except Exception as e:
        logger.debug("섹션 텍스트 추출 실패: %s (오류: %s)", section_path, e)
        return None


def _parse_hwp_text_records(data: bytes) -> str:
    """
    HWP 바이너리 레코드에서 텍스트를 추출합니다.

    HWP 본문 레코드 구조:
    - 헤더: 4바이트 (태그ID 10비트 + 레벨 10비트 + 크기 12비트)
    - 태그ID 67 (HWPTAG_PARA_TEXT): 텍스트 데이터
    """
    texts = []
    offset = 0

    while offset < len(data) - 4:
        try:
            # 레코드 헤더 파싱 (4바이트)
            header = struct.unpack_from("<I", data, offset)[0]
            tag_id = header & 0x3FF           # 하위 10비트: 태그 ID
            # level = (header >> 10) & 0x3FF  # 중간 10비트: 레벨
            size = (header >> 20) & 0xFFF     # 상위 12비트: 크기

            offset += 4

            # 크기가 0xFFF이면 다음 4바이트가 실제 크기
            if size == 0xFFF:
                if offset + 4 > len(data):
                    break
                size = struct.unpack_from("<I", data, offset)[0]
                offset += 4

            # size=0이면 레코드 구조가 손상된 것으로 판단하고 중단
            if size == 0:
                break

            if offset + size > len(data):
                break

            # 태그 ID 67 = HWPTAG_PARA_TEXT (본문 텍스트)
            if tag_id == 67:
                record_data = data[offset : offset + size]
                text = _decode_para_text(record_data)
                if text.strip():
                    texts.append(text)

            offset += size

        except (struct.error, IndexError):
            break

    return "\n".join(texts)


def _decode_para_text(data: bytes) -> str:
    """
    HWPTAG_PARA_TEXT 레코드의 바이너리 데이터를 텍스트로 디코딩합니다.

    HWP 텍스트는 UTF-16LE로 인코딩되어 있으며,
    특수 제어 문자(0x00~0x1F)는 건너뛰어야 합니다.
    제어 문자 중 일부는 확장 데이터를 포함합니다.
    """
    chars = []
    i = 0

    while i < len(data) - 1:
        code = struct.unpack_from("<H", data, i)[0]

        # HWP 인라인 제어 문자 처리
        if code < 0x20:
            if code in (0x00, 0x0D, 0x0A):
                # NULL, CR, LF
                i += 2
            elif code in (
                0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08,
                0x09, 0x0B, 0x0C, 0x0E, 0x0F, 0x10, 0x11, 0x12,
                0x13, 0x14, 0x15, 0x16, 0x17, 0x18, 0x19, 0x1A,
                0x1B, 0x1C, 0x1D, 0x1E, 0x1F,
            ):
                # 확장 제어 문자: 추가 데이터 길이에 따라 건너뜀
                if code in (0x09, 0x0B, 0x0C, 0x0E):
                    # 인라인 확장 (12바이트 추가)
                    i += 16
                else:
                    i += 2
            else:
                i += 2
        else:
            # 일반 문자
            try:
                char = chr(code)
                chars.append(char)
            except (ValueError, OverflowError):
                pass
            i += 2

    return "".join(chars)


def _clean_text(text: str) -> str:
    """
    추출된 텍스트에서 불필요한 문자를 제거하고 정리합니다.

    - 제어 문자 제거 (탭, 줄바꿈 제외)
    - 연속 공백을 단일 공백으로
    - 연속 빈 줄을 최대 2줄로
    """
    # 제어 문자 제거 (탭·줄바꿈은 유지)
    text = re.sub(r"[^\S\t\n\r ]+", "", text)

    # 탭을 공백으로 변환
    text = text.replace("\t", " ")

    # 연속 공백을 단일 공백으로
    text = re.sub(r" {2,}", " ", text)

    # 각 줄 앞뒤 공백 제거
    lines = [line.strip() for line in text.split("\n")]

    # 연속 빈 줄을 최대 1줄로 줄이기
    cleaned_lines = []
    prev_empty = False
    for line in lines:
        if not line:
            if not prev_empty:
                cleaned_lines.append("")
            prev_empty = True
        else:
            cleaned_lines.append(line)
            prev_empty = False

    return "\n".join(cleaned_lines).strip()
