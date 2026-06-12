"""
범용 입찰공고 수집 모듈 (Universal Bid Collector)

나라장터(조달청) 뿐만 아니라 국내외 주요 전자조달 및 용역 플랫폼
(LH 전자조달, K-Startup 지원사업, SAM.gov, UNGM 등)의 공고를 수집하고
공통 스키마로 통합 변환해주는 역할을 수행합니다.
"""

import logging
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Any, Optional

from src.collectors.base_collector import BaseCollector
from src.collectors.bid_collector import BidCollector
from src.models.schemas import BidAnnouncement

logger = logging.getLogger(__name__)


class UniversalBidCollector(BaseCollector):
    """
    범용 입찰/용역 공고 통합 수집기
    
    여러 수집 소스(나라장터, SAM.gov, UNGM, K-Startup 등)를 어댑터 패턴으로 연결하여
    단일 인터페이스를 통해 이종 플랫폼의 공고들을 단일 포맷으로 수집합니다.
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

    def collect_all_sources(self, start_date: str = "", end_date: str = "", platforms: list[str] = None) -> list[BidAnnouncement]:
        """
        선택 또는 활성화된 국내외 소스로부터 공고를 수집하고 통합하여 반환합니다.
        
        Args:
            start_date: YYYYMMDD 형식 시작일 (생략 시 오늘)
            end_date: YYYYMMDD 형식 종료일 (생략 시 오늘)
            platforms: 수집하려는 플랫폼 목록 (예: ['nara', 'kstartup', 'samgov', 'ungm'])
            
        Returns:
            통합된 BidAnnouncement 리스트
        """
        all_bids = []
        
        # platforms가 None이거나 비어있으면 전체 플랫폼 수집
        collect_all = not platforms
        target_platforms = [p.lower() for p in platforms] if platforms else []
        
        # 1. 나라장터 수집 (기존)
        if collect_all or 'nara' in target_platforms:
            try:
                logger.info("UniversalCollector: 나라장터(Nara) 공고 수집 중...")
                if start_date and end_date:
                    nara_bids = self.nara_collector.collect_bids_by_date(start_date, end_date)
                else:
                    nara_bids = self.nara_collector.collect_today_bids()
                all_bids.extend(nara_bids)
                logger.info("UniversalCollector: 나라장터 수집 완료 (%d건)", len(nara_bids))
            except Exception as e:
                logger.error("UniversalCollector: 나라장터 수집 실패: %s", e)

        # 2. 국내 기타 조달망 (K-Startup, LH 등) Mock 수집
        if collect_all or 'kstartup' in target_platforms:
            try:
                logger.info("UniversalCollector: K-Startup 및 국내 기관 조달망 공고 수집 중...")
                k_bids = self._collect_k_startup_mock(start_date, end_date)
                all_bids.extend(k_bids)
                logger.info("UniversalCollector: 국내 타 조달망 수집 완료 (%d건)", len(k_bids))
            except Exception as e:
                logger.error("UniversalCollector: 국내 타 조달망 수집 실패: %s", e)

        # 3. 해외 정부 조달망 (SAM.gov) Mock 수집
        if collect_all or 'samgov' in target_platforms:
            try:
                logger.info("UniversalCollector: 해외 조달망(SAM.gov) 공고 수집 중...")
                sam_bids = self._collect_sam_gov_mock(start_date, end_date)
                all_bids.extend(sam_bids)
                logger.info("UniversalCollector: SAM.gov 수집 완료 (%d건)", len(sam_bids))
            except Exception as e:
                logger.error("UniversalCollector: SAM.gov 수집 실패: %s", e)

        # 4. 국제기구 조달망 (UNGM) Mock 수집
        if collect_all or 'ungm' in target_platforms:
            try:
                logger.info("UniversalCollector: 국제기구 조달망(UNGM) 공고 수집 중...")
                ungm_bids = self._collect_ungm_mock(start_date, end_date)
                all_bids.extend(ungm_bids)
                logger.info("UniversalCollector: UNGM 수집 완료 (%d건)", len(ungm_bids))
            except Exception as e:
                logger.error("UniversalCollector: UNGM 수집 실패: %s", e)

        return all_bids

    def _collect_k_startup_mock(self, start_date: str, end_date: str) -> list[BidAnnouncement]:
        """K-Startup 창업 지원 및 연구개발 용역사업 공고 Mock 수집"""
        now = datetime.now(tz=ZoneInfo("Asia/Seoul"))
        mock_data = [
            {
                "bid_ntce_no": "KS-2026-00452",
                "bid_ntce_ord": "00",
                "title": "2026년 인공지능 기반 창업도약패키지 기술 검증 용역",
                "org_name": "창업진흥원",
                "demand_org_name": "창업진흥원 도약사업부",
                "budget": 28000,  # 2.8억 원
                "bid_begin_dt": now.strftime("%Y-%m-%d 09:00:00"),
                "bid_close_dt": now.strftime("%Y-%m-%d 18:00:00"),
                "category": "SW개발",
                "bid_method": "일반경쟁",
                "contract_method": "협상에 의한 계약",
                "region": "전국",
                "license_limit": "소프트웨어사업자",
                "rfp_url": "https://www.k-startup.go.kr/announcement/KS-2026-00452",
                "rfp_text": "본 용역은 인공지능(AI) 기반 창업기업들의 도약기 기술 검증(PoC) 프로세스를 설계하고 가이드라인을 수립하는 것을 목적으로 합니다. 주요 과업으로는 AI 모델 유효성 평가, 레퍼런스 아키텍처 점검 및 기술 멘토링이 포함됩니다. 경영상태 평가와 유사 사업 실적이 주요 정량 평가 기준입니다."
            }
        ]
        
        bids = []
        for data in mock_data:
            bid = BidAnnouncement.from_dict(data)
            bid.collected_at = now
            bids.append(bid)
        return bids

    def _collect_sam_gov_mock(self, start_date: str, end_date: str) -> list[BidAnnouncement]:
        """미국 연방정부 조달 사이트 SAM.gov Mock 수집"""
        now = datetime.now(tz=ZoneInfo("Asia/Seoul"))
        mock_data = [
            {
                "bid_ntce_no": "SAM-2026-88492",
                "bid_ntce_ord": "01",
                "title": "[SAM.gov] DOD AI Data Quality Assurance and Standard Assessment Service",
                "org_name": "Department of Defense (DOD)",
                "demand_org_name": "Defense Innovation Unit (DIU)",
                "budget": 120000,  # 한화 약 12억 원으로 가정한 금액(만 원 단위)
                "bid_begin_dt": now.strftime("%Y-%m-%d 00:00:00"),
                "bid_close_dt": now.strftime("%Y-%m-%d 23:59:00"),
                "category": "AI",
                "bid_method": "RFP (Request for Proposal)",
                "contract_method": "Best Value Tradeoff",
                "region": "US and Allied Nations",
                "license_limit": "CMMC Level 2, ISO 9001",
                "rfp_url": "https://sam.gov/opp/SAM-2026-88492/view",
                "rfp_text": "This contract aims to design a rigorous data quality assurance framework for military AI models. Requirements include compliance with CMMC level 2 cybersecurity, experience in Department of Defense projects, and robust software engineering practices. A compliance matrix matching our performance work statement (PWS) is mandatory."
            }
        ]
        
        bids = []
        for data in mock_data:
            bid = BidAnnouncement.from_dict(data)
            bid.collected_at = now
            bids.append(bid)
        return bids

    def _collect_ungm_mock(self, start_date: str, end_date: str) -> list[BidAnnouncement]:
        """UNGM (United Nations Global Marketplace) Mock 수집"""
        now = datetime.now(tz=ZoneInfo("Asia/Seoul"))
        mock_data = [
            {
                "bid_ntce_no": "UNGM-2026-00941",
                "bid_ntce_ord": "00",
                "title": "[UNGM] UNDP Global Digital Transformation Consulting and Training Program",
                "org_name": "United Nations Development Programme (UNDP)",
                "demand_org_name": "UNDP Bureau for Policy and Programme Support",
                "budget": 85000,  # 만 원 단위 (약 8.5억 원)
                "bid_begin_dt": now.strftime("%Y-%m-%d 00:00:00"),
                "bid_close_dt": now.strftime("%Y-%m-%d 23:59:00"),
                "category": "컨설팅",
                "bid_method": "RFP",
                "contract_method": "International Competitive Bidding",
                "region": "Global",
                "license_limit": "UNGM Registered Vendor Level 2",
                "rfp_url": "https://www.ungm.org/Public/Notice/UNGM-2026-00941",
                "rfp_text": "UNDP is seeking a partner to support the digital transformation initiatives across multiple developing nations. Tasks include consulting on enterprise architecture, technical training curriculum design, and regional stakeholder workshops. Joint ventures are welcomed to fulfill the international deployment capabilities."
            }
        ]
        
        bids = []
        for data in mock_data:
            bid = BidAnnouncement.from_dict(data)
            bid.collected_at = now
            bids.append(bid)
        return bids
