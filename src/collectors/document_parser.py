"""
문서 파서 통합 모듈

기존 HWP, PDF 파서를 통합 인터페이스로 제공하며,
URL 다운로드 및 텍스트 청킹 기능을 추가로 지원합니다.

지원 파일 형식:
  - HWP (.hwp): src.parsers.hwp_parser를 통한 추출
  - PDF (.pdf): src.parsers.pdf_parser를 통한 추출
"""

import ipaddress
import logging
import os
import re
import socket
import tempfile
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse, unquote

from src.config import ATTACHMENTS_DIR

logger = logging.getLogger(__name__)

# 기존 파서 선택적 임포트
try:
    from src.parsers import hwp_parser

    HWP_PARSER_AVAILABLE = True
except ImportError:
    HWP_PARSER_AVAILABLE = False
    logger.warning(
        "src.parsers.hwp_parser를 임포트할 수 없습니다. "
        "HWP 파일 파싱이 비활성화됩니다."
    )

try:
    from src.parsers import pdf_parser

    PDF_PARSER_AVAILABLE = True
except ImportError:
    PDF_PARSER_AVAILABLE = False
    logger.warning(
        "src.parsers.pdf_parser를 임포트할 수 없습니다. "
        "PDF 파일 파싱이 비활성화됩니다."
    )

# HTTP 요청 라이브러리 선택적 임포트
try:
    import requests

    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False
    logger.warning(
        "requests 라이브러리가 설치되지 않았습니다. "
        "URL 다운로드 기능이 비활성화됩니다. "
        "'pip install requests'로 설치해 주세요."
    )

# 지원하는 파일 확장자 매핑
SUPPORTED_EXTENSIONS = {
    ".hwp": "hwp",
    ".pdf": "pdf",
}

# 다운로드 허용 파일 확장자 (보안: 허용 목록 방식)
ALLOWED_EXTENSIONS = {".hwp", ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".zip"}

# 허용 Content-Type 매핑
ALLOWED_CONTENT_TYPES = {
    "application/pdf",
    "application/x-hwp",
    "application/haansofthwp",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/zip",
    "application/octet-stream",  # 일부 서버가 범용 타입 반환
}

# 다운로드 시 타임아웃 (초)
DOWNLOAD_TIMEOUT = 30

# 다운로드 최대 파일 크기 (100MB)
MAX_DOWNLOAD_SIZE = 100 * 1024 * 1024


class DocumentParser:
    """
    문서 파서 통합 클래스

    HWP, PDF 등 다양한 문서 형식에 대해 통일된
    텍스트 추출 인터페이스를 제공합니다.

    사용 예:
        parser = DocumentParser()
        text = parser.parse_file("/path/to/document.hwp")
        chunks = parser.chunk_text(text, chunk_size=500)
    """

    def __init__(self) -> None:
        """DocumentParser를 초기화합니다."""
        # 기본 저장 디렉터리 생성
        ATTACHMENTS_DIR.mkdir(parents=True, exist_ok=True)
        logger.debug(
            "DocumentParser 초기화 완료 (HWP: %s, PDF: %s)",
            "사용가능" if HWP_PARSER_AVAILABLE else "비활성",
            "사용가능" if PDF_PARSER_AVAILABLE else "비활성",
        )

    def parse_file(self, file_path: str) -> str:
        """
        파일 확장자를 자동 감지하여 텍스트를 추출합니다.

        Args:
            file_path: 파싱할 파일의 절대 또는 상대 경로

        Returns:
            추출된 텍스트 문자열. 실패 시 빈 문자열 반환.
        """
        path = Path(file_path)

        if not path.exists():
            logger.warning("파일을 찾을 수 없습니다: %s", file_path)
            return ""

        ext = path.suffix.lower()

        if ext == ".hwp":
            return self.parse_hwp(str(path))
        elif ext == ".pdf":
            return self.parse_pdf(str(path))
        else:
            logger.warning(
                "지원하지 않는 파일 형식입니다: %s (지원 형식: %s)",
                ext,
                ", ".join(SUPPORTED_EXTENSIONS.keys()),
            )
            return ""

    def parse_hwp(self, file_path: str) -> str:
        """
        HWP 파일에서 텍스트를 추출합니다.

        기존 src.parsers.hwp_parser 모듈에 위임합니다.

        Args:
            file_path: HWP 파일 경로

        Returns:
            추출된 텍스트 문자열. 실패 시 빈 문자열 반환.
        """
        if not HWP_PARSER_AVAILABLE:
            logger.error(
                "HWP 파서를 사용할 수 없습니다. "
                "src.parsers.hwp_parser 모듈을 확인해 주세요."
            )
            return ""

        try:
            text = hwp_parser.extract_text(file_path)
            logger.info(
                "HWP 파싱 완료: %s (텍스트 길이: %d자)",
                Path(file_path).name,
                len(text),
            )
            return text
        except Exception as e:
            logger.error("HWP 파싱 실패: %s (오류: %s)", file_path, e)
            return ""

    def parse_pdf(self, file_path: str) -> str:
        """
        PDF 파일에서 텍스트를 추출합니다.

        기존 src.parsers.pdf_parser 모듈에 위임합니다.

        Args:
            file_path: PDF 파일 경로

        Returns:
            추출된 텍스트 문자열. 실패 시 빈 문자열 반환.
        """
        if not PDF_PARSER_AVAILABLE:
            logger.error(
                "PDF 파서를 사용할 수 없습니다. "
                "src.parsers.pdf_parser 모듈을 확인해 주세요."
            )
            return ""

        try:
            text = pdf_parser.extract_text(file_path)
            logger.info(
                "PDF 파싱 완료: %s (텍스트 길이: %d자)",
                Path(file_path).name,
                len(text),
            )
            return text
        except Exception as e:
            logger.error("PDF 파싱 실패: %s (오류: %s)", file_path, e)
            return ""

    def download_and_parse(
        self,
        url: str,
        save_dir: Optional[str] = None,
    ) -> str:
        """
        URL에서 문서를 다운로드하고 텍스트를 추출합니다.

        Args:
            url: 다운로드할 문서의 URL
            save_dir: 다운로드 파일 저장 디렉터리.
                      None이면 ATTACHMENTS_DIR 사용.

        Returns:
            추출된 텍스트 문자열. 실패 시 빈 문자열 반환.
        """
        if not REQUESTS_AVAILABLE:
            logger.error(
                "requests 라이브러리가 없어 URL 다운로드를 수행할 수 없습니다."
            )
            return ""

        if not url or not url.strip():
            logger.warning("다운로드 URL이 비어있습니다.")
            return ""

        # 저장 디렉터리 결정
        target_dir = Path(save_dir) if save_dir else ATTACHMENTS_DIR
        target_dir.mkdir(parents=True, exist_ok=True)

        # URL에서 파일명 추출
        filename = self._extract_filename_from_url(url)
        if not filename:
            logger.warning("URL에서 파일명을 추출할 수 없습니다: %s", url)
            return ""

        # 지원 형식 확인
        ext = Path(filename).suffix.lower()
        if ext not in SUPPORTED_EXTENSIONS:
            logger.warning(
                "지원하지 않는 파일 형식입니다: %s (URL: %s)",
                ext, url,
            )
            return ""

        save_path = target_dir / filename

        try:
            # SSRF 방어: 내부 네트워크 접근 차단
            if not self._validate_url_safety(url):
                logger.warning("보안 정책에 의해 차단된 URL입니다: %s", url)
                return ""

            # 파일 다운로드
            logger.info("문서 다운로드 시작: %s", url)
            response = requests.get(
                url,
                timeout=DOWNLOAD_TIMEOUT,
                stream=True,
                allow_redirects=False,  # 리다이렉트를 통한 SSRF 우회 방지
            )
            response.raise_for_status()

            # Content-Type 검증
            content_type = response.headers.get("Content-Type", "").split(";")[0].strip().lower()
            if content_type and content_type not in ALLOWED_CONTENT_TYPES:
                logger.warning(
                    "허용되지 않는 Content-Type입니다: %s (URL: %s)",
                    content_type, url,
                )
                return ""

            # Content-Length 확인으로 대용량 파일 방지
            content_length = response.headers.get("Content-Length")
            if content_length:
                try:
                    content_length_int = int(content_length)
                except (ValueError, TypeError):
                    content_length_int = 0
                if content_length_int > MAX_DOWNLOAD_SIZE:
                    logger.warning(
                        "파일이 너무 큽니다: %s bytes (최대: %s bytes)",
                        content_length,
                        MAX_DOWNLOAD_SIZE,
                    )
                    return ""

            # 파일 저장 (스트리밍)
            downloaded_size = 0
            with open(save_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    downloaded_size += len(chunk)
                    if downloaded_size > MAX_DOWNLOAD_SIZE:
                        logger.warning(
                            "다운로드 중 최대 크기 초과: %s", url
                        )
                        # 불완전한 파일 삭제
                        f.close()
                        save_path.unlink(missing_ok=True)
                        return ""
                    f.write(chunk)

            logger.info(
                "문서 다운로드 완료: %s (%d bytes)",
                save_path.name,
                downloaded_size,
            )

            # 다운로드된 파일 파싱
            try:
                return self.parse_file(str(save_path))
            finally:
                # 임시 다운로드 파일 정리
                try:
                    save_path.unlink(missing_ok=True)
                    logger.debug("다운로드 임시 파일 삭제: %s", save_path.name)
                except OSError as cleanup_err:
                    logger.debug("임시 파일 삭제 실패: %s", cleanup_err)

        except requests.exceptions.Timeout:
            logger.error("다운로드 타임아웃: %s (%d초)", url, DOWNLOAD_TIMEOUT)
            return ""
        except requests.exceptions.HTTPError as e:
            logger.error("다운로드 HTTP 오류: %s (상태 코드: %s)", url, e.response.status_code)
            return ""
        except requests.exceptions.RequestException as e:
            logger.error("다운로드 실패: %s (오류: %s)", url, e)
            return ""
        except Exception as e:
            logger.error("다운로드 및 파싱 중 예상치 못한 오류: %s (오류: %s)", url, e)
            return ""

    @staticmethod
    def chunk_text(
        text: str,
        chunk_size: int = 500,
        overlap: int = 50,
    ) -> list[str]:
        """
        텍스트를 겹치는 청크로 분할합니다.

        벡터 DB에 저장하기 위해 긴 텍스트를 적절한
        크기의 조각으로 나눕니다. 문맥 유지를 위해
        청크 간 겹침(overlap)을 적용합니다.

        Args:
            text: 분할할 텍스트
            chunk_size: 각 청크의 최대 문자 수 (기본 500)
            overlap: 청크 간 겹치는 문자 수 (기본 50)

        Returns:
            텍스트 청크 리스트
        """
        if not text or not text.strip():
            return []

        # 파라미터 검증
        if chunk_size <= 0:
            logger.warning("chunk_size는 양수여야 합니다. 기본값(500)을 사용합니다.")
            chunk_size = 500

        if overlap < 0:
            logger.warning("overlap은 0 이상이어야 합니다. 기본값(50)을 사용합니다.")
            overlap = 50

        if overlap >= chunk_size:
            logger.warning(
                "overlap(%d)이 chunk_size(%d)보다 크거나 같습니다. "
                "overlap을 chunk_size의 10%%로 조정합니다.",
                overlap, chunk_size,
            )
            overlap = max(1, chunk_size // 10)

        chunks: list[str] = []
        text = text.strip()
        text_len = len(text)

        # 텍스트가 chunk_size보다 짧으면 그대로 반환
        if text_len <= chunk_size:
            return [text]

        step = chunk_size - overlap
        start = 0

        while start < text_len:
            end = min(start + chunk_size, text_len)

            # 단어 경계를 존중하여 자르기 (마지막 청크가 아닌 경우)
            if end < text_len:
                # 현재 위치에서 뒤로 탐색하여 공백/줄바꿈 위치 찾기
                boundary = end
                while boundary > start and text[boundary] not in (' ', '\n', '\t', '.', ','):
                    boundary -= 1
                # 단어 경계를 찾았으면 그 위치에서 자르기
                if boundary > start:
                    end = boundary + 1  # 구분자 포함

            chunk = text[start:end].strip()

            if chunk:
                chunks.append(chunk)

            # 마지막 청크에 도달하면 종료
            if end >= text_len:
                break

            start = end - overlap if end - overlap > start else start + step

        logger.debug(
            "텍스트 청킹 완료: %d자 → %d개 청크 (크기=%d, 겹침=%d)",
            text_len, len(chunks), chunk_size, overlap,
        )
        return chunks

    @staticmethod
    def _extract_filename_from_url(url: str) -> str:
        """
        URL에서 파일명을 추출합니다.

        경로 순회(path traversal) 공격 방지를 위해
        파일명을 정제(sanitize)합니다.

        Args:
            url: 파일 다운로드 URL

        Returns:
            추출된 파일명. 추출 실패 시 빈 문자열 반환.
        """
        try:
            parsed = urlparse(url)
            path = unquote(parsed.path)

            # URL 경로에서 마지막 부분을 파일명으로 추출
            filename = os.path.basename(path)

            if not filename:
                logger.debug("URL에서 유효한 파일명을 추출할 수 없습니다: %s", url)
                return ""

            # 경로 순회 방어: 위험 문자 제거
            filename = filename.replace("..", "").replace("/", "").replace("\\", "")
            # 추가 정제: 영문, 숫자, 한글, 점, 하이픈, 언더스코어만 허용
            filename = re.sub(r'[^\w가-힣.\-]', '_', filename)

            if not filename or filename.startswith("."):
                logger.debug("정제 후 유효하지 않은 파일명: %s", url)
                return ""

            # 허용 확장자 검증
            ext = Path(filename).suffix.lower()
            if ext not in ALLOWED_EXTENSIONS:
                logger.warning(
                    "허용되지 않는 파일 확장자입니다: %s (허용: %s)",
                    ext, ", ".join(sorted(ALLOWED_EXTENSIONS)),
                )
                return ""

            return filename

        except Exception as e:
            logger.debug("URL 파싱 실패: %s (오류: %s)", url, e)
            return ""

    @staticmethod
    def _is_private_ip(ip_str: str) -> bool:
        """
        IP 주소가 사설/내부 네트워크에 속하는지 확인합니다.

        차단 대상: 127.0.0.0/8, 10.0.0.0/8, 172.16.0.0/12,
        192.168.0.0/16, 169.254.0.0/16, ::1 등

        Args:
            ip_str: 확인할 IP 주소 문자열

        Returns:
            사설/내부 IP이면 True
        """
        try:
            ip = ipaddress.ip_address(ip_str)
            return (
                ip.is_private
                or ip.is_loopback
                or ip.is_link_local
                or ip.is_multicast
                or ip.is_reserved
                or ip.is_unspecified
            )
        except ValueError:
            # 유효하지 않은 IP → 안전을 위해 차단
            return True

    @staticmethod
    def _validate_url_safety(url: str) -> bool:
        """
        SSRF 방어를 위해 URL의 대상 IP가 안전한지 검증합니다.

        호스트명을 DNS로 해석한 뒤 사설/내부 IP 여부를 확인합니다.

        Args:
            url: 검증할 URL

        Returns:
            안전한 URL이면 True, 내부 네트워크이면 False
        """
        try:
            parsed = urlparse(url)
            hostname = parsed.hostname

            if not hostname:
                logger.warning("URL에서 호스트를 추출할 수 없습니다: %s", url)
                return False

            # 스킴 검증: http/https만 허용
            if parsed.scheme not in ("http", "https"):
                logger.warning("허용되지 않는 URL 스킴: %s", parsed.scheme)
                return False

            # DNS 해석으로 실제 IP 확인
            addr_infos = socket.getaddrinfo(hostname, None)
            for addr_info in addr_infos:
                ip_str = addr_info[4][0]
                if DocumentParser._is_private_ip(ip_str):
                    logger.warning(
                        "SSRF 차단: 호스트 '%s'이(가) 내부 IP(%s)로 해석됩니다.",
                        hostname, ip_str,
                    )
                    return False

            return True

        except socket.gaierror:
            logger.warning("DNS 해석 실패: %s", url)
            return False
        except Exception as e:
            logger.warning("URL 안전성 검증 실패: %s (오류: %s)", url, e)
            return False

    def get_supported_formats(self) -> dict[str, bool]:
        """
        지원하는 파일 형식과 현재 사용 가능 여부를 반환합니다.

        Returns:
            파일 형식별 사용 가능 여부 딕셔너리.
            예: {".hwp": True, ".pdf": True}
        """
        return {
            ".hwp": HWP_PARSER_AVAILABLE,
            ".pdf": PDF_PARSER_AVAILABLE,
        }
