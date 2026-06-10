"""
로깅 설정 모듈

파일 로테이션과 JSON 포맷을 지원하는 구조화된 로깅을 설정합니다.
"""

import os
import sys
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from src.config import DATA_DIR


def setup_logging(
    log_level: str | None = None,
    log_file: str | None = None,
    max_bytes: int = 10 * 1024 * 1024,  # 10MB
    backup_count: int = 5,
) -> None:
    """
    애플리케이션 로깅을 설정합니다.

    Args:
        log_level: 로그 레벨 (DEBUG, INFO, WARNING 등). 미지정 시 환경변수 LOG_LEVEL 사용.
        log_file: 로그 파일 경로. 미지정 시 data/nara.log 사용.
        max_bytes: 로그 파일 최대 크기 (바이트)
        backup_count: 로테이션 백업 파일 수
    """
    level = getattr(logging, (log_level or os.getenv("LOG_LEVEL", "INFO")).upper(), logging.INFO)
    
    # 포맷 설정
    fmt = "%(asctime)s [%(levelname)-7s] %(name)s: %(message)s"
    date_fmt = "%Y-%m-%d %H:%M:%S"
    formatter = logging.Formatter(fmt, datefmt=date_fmt)

    # 루트 로거 설정
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # 기존 핸들러 제거 (중복 방지)
    root_logger.handlers.clear()

    # 콘솔 핸들러
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # 파일 핸들러 (로테이션)
    log_path = Path(log_file) if log_file else DATA_DIR / "nara.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        file_handler = RotatingFileHandler(
            str(log_path),
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
    except Exception as e:
        root_logger.warning("파일 로깅 설정 실패: %s", e)

    # 외부 라이브러리 로그 레벨 조절
    logging.getLogger("uvicorn").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("chromadb").setLevel(logging.WARNING)

    root_logger.info("로깅 설정 완료: level=%s, file=%s", logging.getLevelName(level), log_path)
