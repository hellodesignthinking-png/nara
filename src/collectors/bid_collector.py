"""
나라장터 입찰공고 수집 모듈

공공데이터포털 입찰공고정보서비스 API를 호출하여
용역 입찰공고를 수집합니다.

API 문서:
  https://www.data.go.kr/data/15000766/openapi.do
"""

import logging
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Optional

from src.collectors.base_collector import BaseCollector
from src.models.schemas import BidAnnouncement

logger = logging.getLogger(__name__)

# API 상수
BID_API_URL = (
    "https://apis.data.go.kr/1230000/"
    "ad/BidPublicInfoService/getBidPblancListInfoServc"
)
DEFAULT_NUM_OF_ROWS = 100  # 한 페이지당 최대 건수
MAX_PAGES = 100  # 최대 페이지 수 (무한 루프 방지)


class BidCollector(BaseCollector):
    """
    나라장터 입찰공고 수집기

    공공데이터포털 API를 호출하여 용역 입찰공고를 수집하고
    BidAnnouncement 객체 리스트로 반환합니다.

    사용 예:
        from src.config import load_config
        config = load_config()
        collector = BidCollector(config)
        bids = collector.collect_today_bids()
    """

    def __init__(self, config):
        """
        BidCollector 초기화

        Args:
            config: Config 객체 (data_go_kr_api_key 포함)
        """
        super().__init__(config.data_go_kr_api_key)
        self.page_delay = 0.3  # 페이지 간 대기 시간(초)

    def collect_today_bids(self) -> list[BidAnnouncement]:
        """
        오늘 등록된 용역 입찰공고를 수집합니다.

        Returns:
            오늘자 BidAnnouncement 리스트
        """
        today = datetime.now(tz=ZoneInfo("Asia/Seoul"))
        start_date = today.strftime("%Y%m%d") + "0000"
        end_date = today.strftime("%Y%m%d") + "2359"

        logger.info("오늘자 입찰공고 수집 시작: %s", today.strftime("%Y-%m-%d"))

        params = {
            "ServiceKey": self.api_key,
            "numOfRows": str(DEFAULT_NUM_OF_ROWS),
            "pageNo": "1",
            "inqryDiv": "1",               # 검색 구분: 공고일시
            "inqryBgnDt": start_date,       # 조회 시작일시
            "inqryEndDt": end_date,         # 조회 종료일시
            "type": "json",                 # 응답 형식
            "bidNtceNm": "",                # 공고명 (전체)
        }

        bids = self._fetch_all_pages(params)
        logger.info("오늘자 입찰공고 수집 완료: %d건", len(bids))
        return bids

    def collect_bids_by_date(
        self, start_date: str, end_date: str
    ) -> list[BidAnnouncement]:
        """
        특정 기간의 용역 입찰공고를 수집합니다.

        Args:
            start_date: 시작일 (YYYYMMDD 형식)
            end_date: 종료일 (YYYYMMDD 형식)

        Returns:
            해당 기간 BidAnnouncement 리스트
        """
        logger.info("기간별 입찰공고 수집 시작: %s ~ %s", start_date, end_date)

        params = {
            "ServiceKey": self.api_key,
            "numOfRows": str(DEFAULT_NUM_OF_ROWS),
            "pageNo": "1",
            "inqryDiv": "1",
            "inqryBgnDt": start_date + "0000",
            "inqryEndDt": end_date + "2359",
            "type": "json",
        }

        bids = self._fetch_all_pages(params)
        logger.info(
            "기간별 입찰공고 수집 완료: %d건 (%s ~ %s)", len(bids), start_date, end_date
        )
        return bids

    def collect_bids_by_keyword(
        self, keyword: str, days: int = 30, max_results: int = 200
    ) -> list[BidAnnouncement]:
        """
        키워드로 용역 입찰공고를 검색하여 수집합니다.

        나라장터 API의 bidNtceNm(공고명) 파라미터를 사용하여
        해당 키워드가 포함된 공고를 직접 검색합니다.

        Args:
            keyword: 검색 키워드 (예: '소프트웨어', '컨설팅', 'AI')
            days: 검색 기간 (최근 N일, 기본 30일)
            max_results: 최대 수집 건수 (기본 200건, 0이면 무제한)

        Returns:
            키워드 매칭 BidAnnouncement 리스트
        """
        end_dt = datetime.now(tz=ZoneInfo("Asia/Seoul"))
        start_dt = end_dt - timedelta(days=days)

        start_date = start_dt.strftime("%Y%m%d") + "0000"
        end_date = end_dt.strftime("%Y%m%d") + "2359"

        logger.info("키워드 공고 검색 시작: '%s' (최근 %d일, 최대 %d건)", keyword, days, max_results)

        params = {
            "ServiceKey": self.api_key,
            "numOfRows": str(DEFAULT_NUM_OF_ROWS),
            "pageNo": "1",
            "inqryDiv": "1",
            "inqryBgnDt": start_date,
            "inqryEndDt": end_date,
            "type": "json",
            "bidNtceNm": keyword,
        }

        bids = self._fetch_all_pages(params, max_results=max_results)
        logger.info(
            "키워드 공고 검색 완료: '%s' → %d건", keyword, len(bids)
        )
        return bids

    def _fetch_all_pages(self, params: dict, max_results: int = 0) -> list[BidAnnouncement]:
        """
        전체 페이지를 순회하며 모든 공고를 수집합니다.

        API는 페이지네이션을 사용하므로 totalCount를 확인하고
        모든 페이지를 순차적으로 요청합니다.

        Args:
            params: API 요청 파라미터
            max_results: 최대 수집 건수 (0이면 무제한)

        Returns:
            전체 BidAnnouncement 리스트
        """
        all_bids = []
        page = 1
        params = params.copy()  # 호출자의 딕셔너리 변경 방지

        while page <= MAX_PAGES:
            params["pageNo"] = str(page)
            result = self._fetch_page(params, page)

            if result is None:
                # 오류 발생 시 지금까지 수집된 결과 반환
                logger.warning(
                    "페이지 %d 요청 실패, 수집 중단 (현재까지 %d건)", page, len(all_bids)
                )
                break

            items, total_count = result

            if not items:
                break

            all_bids.extend(items)
            logger.debug(
                "페이지 %d 수집 완료: %d건 (누적: %d / 전체: %d)",
                page, len(items), len(all_bids), total_count,
            )

            # max_results 제한 도달 시 조기 종료
            if max_results > 0 and len(all_bids) >= max_results:
                all_bids = all_bids[:max_results]
                logger.info("최대 수집 건수(%d) 도달, 조기 종료", max_results)
                break

            # 모든 페이지를 가져왔는지 확인
            if len(all_bids) >= total_count:
                break

            page += 1
            # API 부하 방지를 위한 짧은 대기
            time.sleep(self.page_delay)

        if page > MAX_PAGES:
            logger.warning("최대 페이지 수(%d) 도달, 수집 중단", MAX_PAGES)

        return all_bids

    def _fetch_page(
        self, params: dict, page: int
    ) -> Optional[tuple[list[BidAnnouncement], int]]:
        """
        특정 페이지의 공고 데이터를 가져옵니다.

        BaseCollector._fetch_with_retry()를 사용하여 재시도를 수행합니다.

        Args:
            params: API 요청 파라미터
            page: 페이지 번호

        Returns:
            (공고 리스트, 전체 건수) 튜플 또는 None (실패 시)
        """
        data = self._fetch_with_retry(BID_API_URL, params)
        if data is None:
            logger.error("페이지 %d 요청 최종 실패", page)
            return None

        try:
            return self._parse_response(data)
        except (ValueError, KeyError) as e:
            logger.warning("페이지 %d 응답 파싱 오류: %s", page, e)
            return None

    def _parse_response(
        self, data: dict
    ) -> tuple[list[BidAnnouncement], int]:
        """
        API 응답 JSON을 BidAnnouncement 리스트로 변환합니다.

        BaseCollector._parse_api_response()로 공통 구조를 파싱한 뒤,
        각 아이템을 BidAnnouncement 객체로 변환합니다.

        Args:
            data: API 응답 JSON 딕셔너리

        Returns:
            (공고 리스트, 전체 건수) 튜플

        Raises:
            ValueError: 응답 형식이 올바르지 않은 경우
        """
        items_raw, total_count = self._parse_api_response(data)

        if not items_raw:
            return [], total_count

        # BidAnnouncement 객체로 변환
        bids = []
        now = datetime.now(tz=ZoneInfo("Asia/Seoul"))

        for item in items_raw:
            try:
                # 추정가격을 정수로 변환
                budget = item.get("presmptPrce")
                if budget:
                    try:
                        budget = int(float(str(budget)))
                    except (ValueError, TypeError):
                        budget = None
                    item["presmptPrce"] = budget

                bid = BidAnnouncement.from_dict(item)
                bid.collected_at = now
                bids.append(bid)

            except Exception as e:
                logger.warning(
                    "공고 데이터 파싱 실패: %s (데이터: %s)",
                    e, item.get("bidNtceNo", "알 수 없음"),
                )
                continue

        return bids, total_count
