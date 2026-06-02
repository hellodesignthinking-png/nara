"""
과거 낙찰정보 수집 모듈

공공데이터포털 낙찰정보서비스 API를 호출하여
키워드 또는 공고번호 기반으로 과거 낙찰정보를 수집합니다.

API 문서:
  https://www.data.go.kr/data/15001395/openapi.do
"""

import logging
import time
from datetime import datetime, timedelta
from typing import Optional

import requests

from src.models.schemas import AwardInfo

logger = logging.getLogger(__name__)

# API 상수
AWARD_API_URL = (
    "https://apis.data.go.kr/1230000/as/ScsbidInfoService"
)
DEFAULT_NUM_OF_ROWS = 100   # 한 페이지당 최대 건수
MAX_RETRIES = 3             # 최대 재시도 횟수
RETRY_DELAY = 2             # 재시도 대기 시간(초)
REQUEST_TIMEOUT = 30        # 요청 타임아웃(초)


class AwardCollector:
    """
    과거 낙찰정보 수집기

    공공데이터포털 낙찰정보서비스 API를 호출하여
    AwardInfo 객체 리스트로 반환합니다.

    사용 예:
        from src.config import load_config
        config = load_config()
        collector = AwardCollector(config)
        awards = collector.collect_awards_by_keyword("인공지능", years_back=2)
    """

    def __init__(self, config):
        """
        AwardCollector 초기화

        Args:
            config: Config 객체 (data_go_kr_api_key 포함)
        """
        self.api_key = config.data_go_kr_api_key
        self.session = requests.Session()

        if not self.api_key:
            logger.warning(
                "공공데이터포털 API 키가 설정되지 않았습니다. "
                "낙찰정보 수집이 불가능합니다."
            )

    def __enter__(self):
        """Context manager 진입: self를 반환합니다."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager 종료: 세션을 정리합니다."""
        self.close()
        return False

    def close(self):
        """내부 requests.Session을 닫고 자원을 해제합니다."""
        if self.session is not None:
            self.session.close()
            self.session = None

    def collect_awards_by_keyword(
        self, keyword: str, years_back: int = 2
    ) -> list[AwardInfo]:
        """
        키워드로 과거 N년간 낙찰정보를 검색합니다.

        Args:
            keyword: 검색 키워드 (공고명 기준)
            years_back: 과거 조회 기간 (년, 기본 2년)

        Returns:
            AwardInfo 리스트
        """
        end_date = datetime.now()
        start_date = end_date - timedelta(days=int(365.25 * years_back))

        logger.info(
            "키워드 낙찰정보 수집 시작: '%s' (%s ~ %s)",
            keyword,
            start_date.strftime("%Y-%m-%d"),
            end_date.strftime("%Y-%m-%d"),
        )

        params = {
            "ServiceKey": self.api_key,
            "numOfRows": str(DEFAULT_NUM_OF_ROWS),
            "pageNo": "1",
            "inqryDiv": "1",
            "inqryBgnDt": start_date.strftime("%Y%m%d") + "0000",
            "inqryEndDt": end_date.strftime("%Y%m%d") + "2359",
            "bidNtceNm": keyword,
            "type": "json",
        }

        awards = self._fetch_all_pages(params)
        logger.info(
            "키워드 낙찰정보 수집 완료: '%s' → %d건", keyword, len(awards)
        )
        return awards

    def collect_awards_by_bid_no(self, bid_ntce_no: str) -> list[AwardInfo]:
        """
        특정 공고의 낙찰정보를 조회합니다.

        Args:
            bid_ntce_no: 입찰공고번호

        Returns:
            AwardInfo 리스트
        """
        logger.info("공고별 낙찰정보 수집 시작: %s", bid_ntce_no)

        params = {
            "ServiceKey": self.api_key,
            "numOfRows": str(DEFAULT_NUM_OF_ROWS),
            "pageNo": "1",
            "bidNtceNo": bid_ntce_no,
            "type": "json",
        }

        awards = self._fetch_all_pages(params)
        logger.info(
            "공고별 낙찰정보 수집 완료: %s → %d건", bid_ntce_no, len(awards)
        )
        return awards

    def _fetch_all_pages(self, params: dict) -> list[AwardInfo]:
        """
        전체 페이지를 순회하며 모든 낙찰정보를 수집합니다.

        Args:
            params: API 요청 파라미터

        Returns:
            전체 AwardInfo 리스트
        """
        all_awards = []
        page = 1
        params = params.copy()  # 호출자의 딕셔너리 변경 방지

        while True:
            params["pageNo"] = str(page)
            result = self._fetch_page(params, page)

            if result is None:
                logger.warning(
                    "페이지 %d 요청 실패, 수집 중단 (현재까지 %d건)",
                    page, len(all_awards),
                )
                break

            items, total_count = result

            if not items:
                break

            all_awards.extend(items)
            logger.debug(
                "페이지 %d 수집 완료: %d건 (누적: %d / 전체: %d)",
                page, len(items), len(all_awards), total_count,
            )

            # 모든 페이지를 가져왔는지 확인
            if len(all_awards) >= total_count:
                break

            page += 1
            # API 부하 방지를 위한 짧은 대기
            time.sleep(0.3)

        return all_awards

    def _fetch_page(
        self, params: dict, page: int
    ) -> Optional[tuple[list[AwardInfo], int]]:
        """
        특정 페이지의 낙찰 데이터를 가져옵니다.

        재시도 로직을 포함하며, 최대 MAX_RETRIES 횟수만큼 재시도합니다.

        Args:
            params: API 요청 파라미터
            page: 페이지 번호

        Returns:
            (낙찰정보 리스트, 전체 건수) 튜플 또는 None (실패 시)
        """
        # close() 호출 후 세션이 해제된 경우 재생성
        if self.session is None:
            logger.warning("세션이 닫혀 있어 새로 생성합니다.")
            self.session = requests.Session()

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = self.session.get(
                    AWARD_API_URL,
                    params=params,
                    timeout=REQUEST_TIMEOUT,
                )
                response.raise_for_status()

                data = response.json()
                return self._parse_response(data)

            except requests.exceptions.HTTPError as e:
                logger.warning(
                    "API HTTP 오류 (페이지 %d, 시도 %d/%d): %s",
                    page, attempt, MAX_RETRIES, e,
                )
            except requests.exceptions.ConnectionError as e:
                logger.warning(
                    "네트워크 연결 오류 (페이지 %d, 시도 %d/%d): %s",
                    page, attempt, MAX_RETRIES, e,
                )
            except requests.exceptions.Timeout as e:
                logger.warning(
                    "요청 타임아웃 (페이지 %d, 시도 %d/%d): %s",
                    page, attempt, MAX_RETRIES, e,
                )
            except requests.exceptions.RequestException as e:
                logger.warning(
                    "요청 오류 (페이지 %d, 시도 %d/%d): %s",
                    page, attempt, MAX_RETRIES, e,
                )
            except (ValueError, KeyError) as e:
                logger.warning(
                    "응답 데이터 파싱 오류 (페이지 %d, 시도 %d/%d): %s",
                    page, attempt, MAX_RETRIES, e,
                )

            # 마지막 시도가 아니면 대기 후 재시도
            if attempt < MAX_RETRIES:
                wait_time = RETRY_DELAY * attempt
                logger.info("%d초 후 재시도...", wait_time)
                time.sleep(wait_time)

        logger.error("페이지 %d 요청 최종 실패 (%d회 시도)", page, MAX_RETRIES)
        return None

    def _parse_response(
        self, data: dict
    ) -> tuple[list[AwardInfo], int]:
        """
        API 응답 JSON을 AwardInfo 리스트로 변환합니다.

        공공데이터포털 응답 구조:
            {
                "response": {
                    "header": {"resultCode": "00", "resultMsg": "NORMAL SERVICE"},
                    "body": {
                        "items": [...],
                        "totalCount": 123,
                        "numOfRows": 100,
                        "pageNo": 1
                    }
                }
            }

        Args:
            data: API 응답 JSON 딕셔너리

        Returns:
            (낙찰정보 리스트, 전체 건수) 튜플

        Raises:
            ValueError: 응답 형식이 올바르지 않은 경우
        """
        # 응답 헤더 확인
        response = data.get("response", {})
        header = response.get("header", {})
        result_code = header.get("resultCode", "")

        if result_code != "00":
            result_msg = header.get("resultMsg", "알 수 없는 오류")
            raise ValueError(f"API 오류 응답: [{result_code}] {result_msg}")

        body = response.get("body", {})
        total_count = int(body.get("totalCount", 0))

        if total_count == 0:
            return [], 0

        # items 추출 (단건일 때 딕셔너리로 올 수 있음)
        items_raw = body.get("items", [])
        if isinstance(items_raw, dict):
            items_raw = items_raw.get("item", [])
        if isinstance(items_raw, dict):
            items_raw = [items_raw]
        if not isinstance(items_raw, list):
            items_raw = []

        # AwardInfo 객체로 변환
        awards = []
        now = datetime.now()

        for item in items_raw:
            try:
                award = AwardInfo.from_dict(item)
                award.collected_at = now
                awards.append(award)
            except Exception as e:
                logger.debug(
                    "낙찰정보 파싱 실패: %s (데이터: %s)",
                    e, item.get("bidNtceNo", "알 수 없음"),
                )
                continue

        return awards, total_count
