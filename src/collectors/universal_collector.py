"""
범용 입찰공고 수집 모듈 (Universal Bid Collector)

나라장터(조달청) 뿐만 아니라 국내 주요 전자조달 및 용역 플랫폼
(K-Startup 지원사업, 아르코, 서울문화재단, 콘텐츠진흥원, e나라도움 등)의
공고를 수집하고 공통 스키마로 통합 변환해주는 역할을 수행합니다.
"""

import logging
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Any, Optional

from src.collectors.base_collector import BaseCollector
from src.collectors.bid_collector import BidCollector
from src.collectors.culture_collector import CultureBidCollector
from src.models.schemas import BidAnnouncement

logger = logging.getLogger(__name__)


class UniversalBidCollector(BaseCollector):
    """
    범용 입찰/용역 공고 통합 수집기

    여러 수집 소스(나라장터, K-Startup, 아르코, 서울문화재단 등)를
    어댑터 패턴으로 연결하여 단일 인터페이스를 통해 이종 플랫폼의
    공고들을 단일 포맷으로 수집합니다.
    """

    def __init__(self, config):
        """
        UniversalBidCollector 초기화

        Args:
            config: Config 객체
        """
        super().__init__(config.data_go_kr_api_key)
        self.config = config
        self.nara_collector = BidCollector(config)
        self.culture_collector = CultureBidCollector(config)

    def collect_all_sources(self, start_date: str = "", end_date: str = "", platforms: list[str] = None, keyword: str = "") -> list[BidAnnouncement]:
        """
        선택 또는 활성화된 국내 소스로부터 공고를 수집하고 통합하여 반환합니다.

        Args:
            start_date: YYYYMMDD 형식 시작일 (생략 시 오늘)
            end_date: YYYYMMDD 형식 종료일 (생략 시 오늘)
            platforms: 수집하려는 플랫폼 목록
                (예: ['nara', 'kstartup', 'arko', 'sfac', 'kocca', 'e_naradoum'])
            keyword: 공고명 필터링 키워드

        Returns:
            통합된 BidAnnouncement 리스트
        """
        all_bids = []

        # platforms가 None이거나 비어있으면 전체 플랫폼 수집
        collect_all = not platforms
        target_platforms = [p.lower() for p in platforms] if platforms else []

        # 1. 나라장터 수집 (기존 — 실제 API)
        if collect_all or 'nara' in target_platforms:
            try:
                logger.info("UniversalCollector: 나라장터(Nara) 공고 수집 중...")
                if keyword:
                    days = 30
                    if start_date and end_date:
                        try:
                            d1 = datetime.strptime(start_date, "%Y%m%d")
                            d2 = datetime.strptime(end_date, "%Y%m%d")
                            days = max(1, (d2 - d1).days)
                        except Exception:
                            pass
                    nara_bids = self.nara_collector.collect_bids_by_keyword(keyword, days=days)
                elif start_date and end_date:
                    nara_bids = self.nara_collector.collect_bids_by_date(start_date, end_date)
                else:
                    nara_bids = self.nara_collector.collect_today_bids()
                all_bids.extend(nara_bids)
                logger.info("UniversalCollector: 나라장터 수집 완료 (%d건)", len(nara_bids))
            except Exception as e:
                logger.error("UniversalCollector: 나라장터 수집 실패: %s", e)

        # 2. K-Startup 창업 지원사업 (실제 API 미연동 — 건너뜀)
        if collect_all or 'kstartup' in target_platforms:
            logger.info("UniversalCollector: K-Startup API 미연동 상태 — 건너뜁니다.")

        # 3. 한국문화예술위원회 (아르코)
        if collect_all or 'arko' in target_platforms:
            try:
                logger.info("UniversalCollector: 아르코(ARKO) 공고 수집 중...")
                arko_bids = self.culture_collector.collect_arko(start_date, end_date)
                all_bids.extend(arko_bids)
                logger.info("UniversalCollector: 아르코 수집 완료 (%d건)", len(arko_bids))
            except Exception as e:
                logger.error("UniversalCollector: 아르코 수집 실패: %s", e)

        # 4. 서울문화재단 (SFAC)
        if collect_all or 'sfac' in target_platforms:
            try:
                logger.info("UniversalCollector: 서울문화재단(SFAC) 공고 수집 중...")
                sfac_bids = self.culture_collector.collect_sfac(start_date, end_date)
                all_bids.extend(sfac_bids)
                logger.info("UniversalCollector: 서울문화재단 수집 완료 (%d건)", len(sfac_bids))
            except Exception as e:
                logger.error("UniversalCollector: 서울문화재단 수집 실패: %s", e)

        # 5. 한국콘텐츠진흥원 (KOCCA)
        if 'kocca' in target_platforms:
            try:
                logger.info("UniversalCollector: 콘텐츠진흥원(KOCCA) 공고 수집 중...")
                kocca_bids = self.culture_collector.collect_kocca(start_date, end_date)
                all_bids.extend(kocca_bids)
                logger.info("UniversalCollector: 콘텐츠진흥원 수집 완료 (%d건)", len(kocca_bids))
            except Exception as e:
                logger.error("UniversalCollector: 콘텐츠진흥원 수집 실패: %s", e)

        # 6. e나라도움 / 보조금24
        if 'e_naradoum' in target_platforms:
            try:
                logger.info("UniversalCollector: e나라도움 보조금 공모 수집 중...")
                enara_bids = self.culture_collector.collect_e_naradoum(start_date, end_date)
                all_bids.extend(enara_bids)
                logger.info("UniversalCollector: e나라도움 수집 완료 (%d건)", len(enara_bids))
            except Exception as e:
                logger.error("UniversalCollector: e나라도움 수집 실패: %s", e)

        # 7. 예술경영지원센터 (GOKAMS)
        if collect_all or 'gokams' in target_platforms:
            try:
                logger.info("UniversalCollector: 예술경영지원센터(GOKAMS) 공고 수집 중...")
                gokams_bids = self.culture_collector.collect_gokams(start_date, end_date)
                all_bids.extend(gokams_bids)
                logger.info("UniversalCollector: 예술경영지원센터 수집 완료 (%d건)", len(gokams_bids))
            except Exception as e:
                logger.error("UniversalCollector: 예술경영지원센터 수집 실패: %s", e)

        # 8. 한국공예디자인문화진흥원 (KCDF)
        if collect_all or 'kcdf' in target_platforms:
            try:
                logger.info("UniversalCollector: 공예디자인진흥원(KCDF) 공고 수집 중...")
                kcdf_bids = self.culture_collector.collect_kcdf(start_date, end_date)
                all_bids.extend(kcdf_bids)
                logger.info("UniversalCollector: 공예디자인진흥원 수집 완료 (%d건)", len(kcdf_bids))
            except Exception as e:
                logger.error("UniversalCollector: 공예디자인진흥원 수집 실패: %s", e)

        # 9. 한국관광공사
        if 'visitkorea' in target_platforms:
            try:
                logger.info("UniversalCollector: 한국관광공사 공고 수집 중...")
                kto_bids = self.culture_collector.collect_visitkorea(start_date, end_date)
                all_bids.extend(kto_bids)
                logger.info("UniversalCollector: 한국관광공사 수집 완료 (%d건)", len(kto_bids))
            except Exception as e:
                logger.error("UniversalCollector: 한국관광공사 수집 실패: %s", e)

        # 10. LH 한국토지주택공사
        if 'lh' in target_platforms:
            try:
                logger.info("UniversalCollector: LH 전자조달 공고 수집 중...")
                lh_bids = self.culture_collector.collect_lh(start_date, end_date)
                all_bids.extend(lh_bids)
                logger.info("UniversalCollector: LH 전자조달 수집 완료 (%d건)", len(lh_bids))
            except Exception as e:
                logger.error("UniversalCollector: LH 전자조달 수집 실패: %s", e)

        # 11. 한국연구재단 (NRF)
        if 'nrf' in target_platforms:
            try:
                logger.info("UniversalCollector: 한국연구재단(NRF) 공고 수집 중...")
                nrf_bids = self.culture_collector.collect_nrf(start_date, end_date)
                all_bids.extend(nrf_bids)
                logger.info("UniversalCollector: 한국연구재단 수집 완료 (%d건)", len(nrf_bids))
            except Exception as e:
                logger.error("UniversalCollector: 한국연구재단 수집 실패: %s", e)

        return all_bids

