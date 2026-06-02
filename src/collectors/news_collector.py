"""
네이버 뉴스 검색 수집 모듈

네이버 검색 API를 호출하여 키워드 관련 뉴스 기사를 수집합니다.
발주기관 동향 파악 및 입찰공고 관련 뉴스 분석에 활용됩니다.

API 문서:
  https://developers.naver.com/docs/serviceapi/search/news/news.md
"""

import html as html_mod
import logging
import re
import time
from datetime import datetime, timedelta
from typing import Optional

import requests

from src.models.schemas import NewsArticle

logger = logging.getLogger(__name__)

# API 상수
NEWS_API_URL = "https://openapi.naver.com/v1/search/news.json"
MAX_DISPLAY = 100           # 한 번에 최대 반환 건수
MAX_START = 1000            # 검색 시작 위치 최대값 (API 제한)
MAX_RETRIES = 3             # 최대 재시도 횟수
RETRY_DELAY = 1             # 재시도 대기 시간(초)
REQUEST_TIMEOUT = 15        # 요청 타임아웃(초)
DAILY_LIMIT = 25_000        # 일일 API 호출 제한


class NewsCollector:
    """
    네이버 뉴스 검색 수집기

    네이버 검색 API를 호출하여 뉴스 기사를 수집하고
    NewsArticle 객체 리스트로 반환합니다.

    일일 25,000건 호출 제한이 있으므로 과도한 요청에 주의해야 합니다.

    사용 예:
        from src.config import load_config
        config = load_config()
        collector = NewsCollector(config)
        news = collector.search_news("인공지능 입찰", display=10)
    """

    def __init__(self, config):
        """
        NewsCollector 초기화

        Args:
            config: Config 객체 (naver_client_id, naver_client_secret 포함)
        """
        self.client_id = config.naver_client_id
        self.client_secret = config.naver_client_secret
        self.session = requests.Session()

        # 인증 헤더 설정
        if self.client_id and self.client_secret:
            self.session.headers.update({
                "X-Naver-Client-Id": self.client_id,
                "X-Naver-Client-Secret": self.client_secret,
            })
        else:
            logger.warning(
                "네이버 API 키가 설정되지 않았습니다. "
                "뉴스 수집이 불가능합니다."
            )

        # 일일 호출 횟수 추적 (간이 카운터)
        self._daily_call_count = 0
        self._count_reset_date = datetime.now().date()

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

    def _check_daily_limit(self) -> bool:
        """
        일일 호출 제한을 확인합니다.

        Returns:
            호출 가능 여부
        """
        today = datetime.now().date()
        if today != self._count_reset_date:
            # 날짜가 바뀌면 카운터 초기화
            self._daily_call_count = 0
            self._count_reset_date = today

        if self._daily_call_count >= DAILY_LIMIT:
            logger.warning(
                "네이버 API 일일 호출 한도 초과: %d / %d",
                self._daily_call_count, DAILY_LIMIT,
            )
            return False
        return True

    def search_news(
        self,
        query: str,
        display: int = 10,
        sort: str = "date",
    ) -> list[NewsArticle]:
        """
        키워드로 뉴스를 검색합니다.

        Args:
            query: 검색 키워드
            display: 반환 건수 (기본 10, 최대 100)
            sort: 정렬 기준 ('date': 최신순, 'sim': 관련도순)

        Returns:
            NewsArticle 리스트
        """
        if not self.client_id or not self.client_secret:
            logger.error("네이버 API 인증 정보가 없습니다.")
            return []

        if not self._check_daily_limit():
            return []

        display = min(display, MAX_DISPLAY)

        logger.info("뉴스 검색: '%s' (건수: %d, 정렬: %s)", query, display, sort)

        params = {
            "query": query,
            "display": display,
            "start": 1,
            "sort": sort,
        }

        articles = self._fetch_news(params, query)

        logger.info("뉴스 검색 완료: '%s' → %d건", query, len(articles))
        return articles

    def collect_org_news(
        self,
        org_name: str,
        keywords: Optional[list[str]] = None,
        years_back: int = 1,
    ) -> list[NewsArticle]:
        """
        발주기관 관련 뉴스를 수집합니다.

        기관명과 키워드를 조합하여 관련 뉴스를 검색합니다.

        Args:
            org_name: 발주기관명
            keywords: 추가 검색 키워드 목록 (None이면 기관명만으로 검색)
            years_back: 과거 조회 기간 (년, 기본 1년)

        Returns:
            NewsArticle 리스트
        """
        if not self.client_id or not self.client_secret:
            logger.error("네이버 API 인증 정보가 없습니다.")
            return []

        all_articles = []

        # 날짜 범위 계산 (네이버 API d_from/d_to 형식: YYYYMMDD)
        end_dt = datetime.now()
        start_dt = end_dt - timedelta(days=int(365.25 * years_back))
        d_from = start_dt.strftime("%Y%m%d")
        d_to = end_dt.strftime("%Y%m%d")

        # 1. 기관명 단독 검색
        logger.info(
            "발주기관 뉴스 수집 시작: '%s' (기간: %s ~ %s)",
            org_name, d_from, d_to,
        )
        articles = self._search_news_with_date(
            org_name, display=20, sort="date", d_from=d_from, d_to=d_to,
        )
        all_articles.extend(articles)

        # 2. 기관명 + 키워드 조합 검색
        if keywords:
            for keyword in keywords:
                if not self._check_daily_limit():
                    logger.warning("일일 호출 한도에 도달, 수집 중단")
                    break

                combined_query = f"{org_name} {keyword}"
                articles = self._search_news_with_date(
                    combined_query, display=10, sort="date",
                    d_from=d_from, d_to=d_to,
                )
                all_articles.extend(articles)

                # API 부하 방지
                time.sleep(0.2)

        # 중복 제거 (링크 기준)
        seen_links = set()
        unique_articles = []
        for article in all_articles:
            if article.link and article.link not in seen_links:
                seen_links.add(article.link)
                unique_articles.append(article)

        logger.info(
            "발주기관 뉴스 수집 완료: '%s' → %d건 (중복 제거 전: %d건)",
            org_name, len(unique_articles), len(all_articles),
        )
        return unique_articles

    def _search_news_with_date(
        self,
        query: str,
        display: int = 10,
        sort: str = "date",
        d_from: Optional[str] = None,
        d_to: Optional[str] = None,
    ) -> list[NewsArticle]:
        """
        날짜 범위를 지정하여 뉴스를 검색합니다.

        Args:
            query: 검색 키워드
            display: 반환 건수 (기본 10, 최대 100)
            sort: 정렬 기준 ('date': 최신순, 'sim': 관련도순)
            d_from: 검색 시작일 (YYYYMMDD)
            d_to: 검색 종료일 (YYYYMMDD)

        Returns:
            NewsArticle 리스트
        """
        if not self.client_id or not self.client_secret:
            logger.error("네이버 API 인증 정보가 없습니다.")
            return []

        if not self._check_daily_limit():
            return []

        display = min(display, MAX_DISPLAY)

        params = {
            "query": query,
            "display": display,
            "start": 1,
            "sort": sort,
        }
        if d_from:
            params["d_from"] = d_from
        if d_to:
            params["d_to"] = d_to

        articles = self._fetch_news(params, query)
        return articles

    def _fetch_news(self, params: dict, query: str) -> list[NewsArticle]:
        """
        네이버 뉴스 검색 API를 호출합니다.

        재시도 로직을 포함하며, HTML 태그 제거 등 후처리를 수행합니다.

        Args:
            params: API 요청 파라미터
            query: 원본 검색어 (메타데이터용)

        Returns:
            NewsArticle 리스트
        """
        # close() 호출 후 세션이 해제된 경우 재생성
        if self.session is None:
            logger.warning("세션이 닫혀 있어 새로 생성합니다.")
            self.session = requests.Session()
            if self.client_id and self.client_secret:
                self.session.headers.update({
                    "X-Naver-Client-Id": self.client_id,
                    "X-Naver-Client-Secret": self.client_secret,
                })

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = self.session.get(
                    NEWS_API_URL,
                    params=params,
                    timeout=REQUEST_TIMEOUT,
                )
                self._daily_call_count += 1

                # HTTP 오류 확인
                if response.status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", RETRY_DELAY * attempt))
                    logger.warning(
                        "네이버 API 호출 한도 초과 (429), %d초 후 재시도 (시도 %d/%d)",
                        retry_after, attempt, MAX_RETRIES,
                    )
                    if attempt < MAX_RETRIES:
                        time.sleep(retry_after)
                        continue
                    return []

                response.raise_for_status()

                data = response.json()
                return self._parse_response(data, query)

            except requests.exceptions.HTTPError as e:
                logger.warning(
                    "API HTTP 오류 (시도 %d/%d): %s",
                    attempt, MAX_RETRIES, e,
                )
            except requests.exceptions.ConnectionError as e:
                logger.warning(
                    "네트워크 연결 오류 (시도 %d/%d): %s",
                    attempt, MAX_RETRIES, e,
                )
            except requests.exceptions.Timeout as e:
                logger.warning(
                    "요청 타임아웃 (시도 %d/%d): %s",
                    attempt, MAX_RETRIES, e,
                )
            except requests.exceptions.RequestException as e:
                logger.warning(
                    "요청 오류 (시도 %d/%d): %s",
                    attempt, MAX_RETRIES, e,
                )
            except (ValueError, KeyError) as e:
                logger.warning(
                    "응답 파싱 오류 (시도 %d/%d): %s",
                    attempt, MAX_RETRIES, e,
                )

            # 마지막 시도가 아니면 대기 후 재시도
            if attempt < MAX_RETRIES:
                wait_time = RETRY_DELAY * attempt
                logger.info("%d초 후 재시도...", wait_time)
                time.sleep(wait_time)

        logger.error("뉴스 검색 최종 실패: '%s' (%d회 시도)", query, MAX_RETRIES)
        return []

    def _parse_response(
        self, data: dict, query: str
    ) -> list[NewsArticle]:
        """
        네이버 뉴스 검색 API 응답을 NewsArticle 리스트로 변환합니다.

        네이버 검색 API 응답 구조:
            {
                "lastBuildDate": "...",
                "total": 12345,
                "start": 1,
                "display": 10,
                "items": [
                    {
                        "title": "...",
                        "originallink": "...",
                        "link": "...",
                        "description": "...",
                        "pubDate": "..."
                    },
                    ...
                ]
            }

        Args:
            data: API 응답 JSON 딕셔너리
            query: 검색 키워드

        Returns:
            NewsArticle 리스트
        """
        items = data.get("items", [])
        if not isinstance(items, list):
            return []

        articles = []
        now = datetime.now()

        for item in items:
            try:
                # HTML 태그 제거
                title = self._strip_html(item.get("title", ""))
                description = self._strip_html(item.get("description", ""))

                # 원본 링크 우선 사용
                link = item.get("originallink") or item.get("link", "")

                article = NewsArticle(
                    title=title,
                    description=description,
                    link=link,
                    pub_date=item.get("pubDate"),
                    search_query=query,
                    related_bid_no=None,
                    collected_at=now,
                )
                articles.append(article)

            except Exception as e:
                logger.debug("뉴스 아이템 파싱 실패: %s", e)
                continue

        return articles

    @staticmethod
    def _strip_html(text: str) -> str:
        """
        문자열에서 HTML 태그를 제거합니다.

        네이버 API 응답의 title, description에는
        <b>, </b> 등 HTML 태그가 포함되어 있습니다.

        Args:
            text: HTML이 포함된 문자열

        Returns:
            태그가 제거된 순수 텍스트
        """
        if not text:
            return ""
        # HTML 태그 제거
        clean = re.sub(r"<[^>]+>", "", text)
        # HTML 엔티티 변환 (html.unescape로 모든 엔티티를 처리)
        clean = html_mod.unescape(clean)
        return clean.strip()
