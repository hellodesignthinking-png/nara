"""
수집기 공통 기본 클래스 모듈

세션 관리, 지수 백오프 재시도, 공공데이터포털 API 응답 파싱 등
수집기 간 중복 로직을 통합합니다.
"""

import logging
import random
import time
from typing import Optional

import requests

logger = logging.getLogger(__name__)


class BaseCollector:
    """나라장터 API 수집기 공통 기본 클래스

    재시도 로직, 세션 관리, 응답 파싱 등
    수집기 공통 로직을 제공합니다.
    """

    MAX_RETRIES = 3
    BASE_RETRY_DELAY = 2  # 초
    REQUEST_TIMEOUT = 30  # 초

    def __init__(self, api_key: str = ""):
        self.api_key = api_key
        self.session = requests.Session()

        if not api_key:
            logger.warning(
                "%s: API 키가 설정되지 않았습니다.", self.__class__.__name__
            )

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    def close(self):
        if self.session is not None:
            self.session.close()
            self.session = None

    def _ensure_session(self) -> requests.Session:
        if self.session is None:
            logger.debug("세션이 닫혀 있어 새로 생성합니다.")
            self.session = requests.Session()
        return self.session

    def _fetch_with_retry(
        self,
        url: str,
        params: dict,
        max_retries: Optional[int] = None,
    ) -> Optional[dict]:
        """지수 백오프 + 지터를 적용한 재시도 HTTP GET 요청"""
        session = self._ensure_session()
        retries = max_retries if max_retries is not None else self.MAX_RETRIES

        for attempt in range(1, retries + 1):
            try:
                response = session.get(url, params=params, timeout=self.REQUEST_TIMEOUT)

                # 429 Rate Limit 시 Retry-After 존중
                if response.status_code == 429:
                    try:
                        wait_time = int(response.headers.get("Retry-After", 5))
                    except (ValueError, TypeError):
                        wait_time = 5
                    logger.warning("API 호출 제한 (429), %d초 후 재시도", wait_time)
                    time.sleep(wait_time)
                    continue

                response.raise_for_status()

                # Content-Type 확인 후 JSON 파싱
                content_type = response.headers.get("Content-Type", "")
                if "application/json" not in content_type:
                    logger.warning("예상치 못한 Content-Type: %s", content_type)
                    return None
                return response.json()

            except requests.exceptions.HTTPError as e:
                logger.warning(
                    "HTTP 오류 (시도 %d/%d): %s", attempt, retries, e
                )
            except requests.exceptions.ConnectionError as e:
                logger.warning(
                    "네트워크 연결 오류 (시도 %d/%d): %s", attempt, retries, e
                )
            except requests.exceptions.Timeout as e:
                logger.warning(
                    "요청 타임아웃 (시도 %d/%d): %s", attempt, retries, e
                )
            except requests.exceptions.RequestException as e:
                logger.warning(
                    "요청 오류 (시도 %d/%d): %s", attempt, retries, e
                )
            except (ValueError, KeyError) as e:
                logger.warning(
                    "응답 파싱 오류 (시도 %d/%d): %s", attempt, retries, e
                )

            # 마지막 시도가 아니면 지수 백오프 + 지터 적용
            if attempt < retries:
                delay = self.BASE_RETRY_DELAY * (2 ** (attempt - 1))
                jitter = random.uniform(0, delay * 0.5)
                wait_time = delay + jitter
                logger.info("%.1f초 후 재시도...", wait_time)
                time.sleep(wait_time)

        logger.error("요청 최종 실패 (%d회 시도)", retries)
        return None

    def _parse_api_response(self, data: dict) -> tuple[list[dict], int]:
        """공공데이터포털 API 응답 구조를 파싱합니다.

        Returns:
            (items 리스트, 전체 건수) 튜플

        Raises:
            ValueError: 응답 형식 오류 시
        """
        response_data = data.get("response", {})
        header = response_data.get("header", {})
        result_code = header.get("resultCode", "")

        if result_code != "00":
            result_msg = header.get("resultMsg", "알 수 없는 오류")
            raise ValueError(f"API 오류 응답: [{result_code}] {result_msg}")

        body = response_data.get("body", {})
        total_count = int(body.get("totalCount", 0))

        if total_count == 0:
            return [], 0

        items_raw = body.get("items", [])
        if isinstance(items_raw, dict):
            items_raw = items_raw.get("item", [])
        if isinstance(items_raw, dict):
            items_raw = [items_raw]
        if not isinstance(items_raw, list):
            items_raw = []

        return items_raw, total_count
