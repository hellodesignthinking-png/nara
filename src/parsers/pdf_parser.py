"""
PDF 파일 텍스트 추출 모듈

pdfplumber 라이브러리를 사용하여 PDF 파일에서
텍스트를 추출합니다. 모든 페이지의 텍스트를 합쳐서 반환합니다.
"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# 최대 처리 페이지 수
MAX_PAGES = 100


def extract_text(file_path: str) -> str:
    """
    PDF 파일에서 텍스트를 추출합니다.

    모든 페이지의 텍스트를 순서대로 합쳐서 반환합니다.

    Args:
        file_path: PDF 파일 경로

    Returns:
        추출된 텍스트 문자열. 실패 시 빈 문자열 반환.
    """
    try:
        # pdfplumber는 선택적 의존성이므로 런타임에 임포트
        import pdfplumber
    except ImportError:
        logger.warning(
            "pdfplumber 라이브러리가 설치되지 않았습니다. "
            "'pip install pdfplumber'로 설치해 주세요."
        )
        return ""

    file_path = Path(file_path)
    if not file_path.exists():
        logger.warning("PDF 파일을 찾을 수 없습니다: %s", file_path)
        return ""

    try:
        pages_text = []

        with pdfplumber.open(file_path) as pdf:
            total_pages = len(pdf.pages)
            pages_to_process = min(total_pages, MAX_PAGES)
            if total_pages > MAX_PAGES:
                logger.warning(
                    "PDF 페이지 수(%d)가 최대 처리 수(%d)를 초과합니다. 앞부분만 처리합니다.",
                    total_pages, MAX_PAGES,
                )
            logger.info("PDF 파일 열기 완료: %s (총 %d페이지, 처리: %d페이지)", file_path.name, total_pages, pages_to_process)

            for i, page in enumerate(pdf.pages[:pages_to_process]):
                try:
                    text = page.extract_text()
                    if text:
                        pages_text.append(text)
                except Exception as e:
                    logger.debug(
                        "PDF %d번째 페이지 텍스트 추출 실패: %s (오류: %s)",
                        i + 1, file_path.name, e,
                    )
                    continue

        result = "\n\n".join(pages_text).strip()

        logger.info(
            "PDF 텍스트 추출 완료: %s (길이: %d자, %d/%d 페이지 성공)",
            file_path.name,
            len(result),
            len(pages_text),
            total_pages,
        )
        return result

    except Exception as e:
        logger.warning("PDF 텍스트 추출 중 오류 발생: %s (오류: %s)", file_path, e)
        return ""
