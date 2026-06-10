"""
전략 엔진 모듈

모든 수집·분석 데이터를 종합하여 최종 입찰 전략 보고서를 생성합니다.
LLM 분석기를 활용하여 경쟁사 분석, 차별화 전략, 리스크 평가,
예산 분석, 행동 체크리스트를 포함한 종합 전략을 수립합니다.
"""

import logging
import time
from datetime import datetime
from .llm_analyzer import LLMAnalyzer

logger = logging.getLogger(__name__)


class StrategyEngine:
    """
    입찰 전략 종합 엔진

    키워드 필터, 사업자 매칭, LLM 분석 결과를 모두 통합하여
    실무에 바로 활용할 수 있는 전략 보고서를 생성합니다.
    """

    def __init__(self, llm_analyzer: LLMAnalyzer, config=None):
        """
        전략 엔진을 초기화합니다.

        Args:
            llm_analyzer: LLM 분석기 인스턴스
            config: 설정 객체 (api_delay 속성 지원, 선택)
        """
        self.llm = llm_analyzer
        self.api_delay = getattr(config, 'api_delay', 1.0) if config else 1.0

    def generate_strategy(
        self,
        bid: dict,
        business_profile: dict,
        rfp_text: str = '',
        past_awards: list[dict] | None = None,
        news_articles: list[dict] | None = None,
    ) -> dict:
        """
        최종 전략 보고서를 생성합니다.

        수집된 모든 데이터를 LLM에 전달하여 종합 분석을 수행하고,
        추가적인 메타 정보(분석 시각, 데이터 소스 현황 등)를 첨부합니다.

        Args:
            bid: 공고 정보 dict
            business_profile: 사업자 프로필 dict
            rfp_text: RFP 본문 텍스트
            past_awards: 과거 낙찰 이력 리스트
            news_articles: 관련 뉴스 기사 리스트

        Returns:
            {
                'bid_info': { ... },                    # 공고 기본 정보
                'bid_summary': '...',                   # 사업 핵심 방향 분석
                'competitor_analysis': '...',           # 경쟁사 분석
                'differentiation_strategy': '...',      # 차별화 전략
                'risk_factors': '...',                  # 주의사항
                'budget_analysis': '...',               # 예산 분석
                'action_items': ['...', ...],           # 준비 체크리스트
                'overall_recommendation': '...',        # 종합 권고
                'metadata': {                           # 분석 메타 정보
                    'analyzed_at': '...',
                    'data_sources': { ... },
                    'analysis_engine': '...',
                },
            }
        """
        past_awards = past_awards or []
        news_articles = news_articles or []

        logger.info("전략 분석 시작: %s", bid.get('title', bid.get('bidNtceNm', '')))

        # ─── 1단계: LLM 컨텍스트 분석 ───
        llm_result = self.llm.analyze_with_context(
            bid=bid,
            rfp_text=rfp_text,
            past_awards=past_awards,
            news_articles=news_articles,
            business_profile=business_profile,
        )

        # ─── 2단계: 공고 기본 정보 정리 ───
        bid_info = self._extract_bid_info(bid)

        # ─── 3단계: 데이터 소스 현황 정리 ───
        data_sources = {
            'rfp_available': bool(rfp_text),
            'rfp_length': len(rfp_text) if rfp_text else 0,
            'past_awards_count': len(past_awards),
            'news_articles_count': len(news_articles),
            'business_profile_available': bool(business_profile),
        }

        # ─── 4단계: 행동 체크리스트 보강 ───
        action_items = llm_result.get('action_items', [])
        action_items = self._enrich_action_items(action_items, bid, business_profile)

        # ─── 5단계: 최종 전략 보고서 조립 ───
        strategy_report = {
            'bid_info': bid_info,
            'bid_summary': llm_result.get('bid_summary', ''),
            'org_policy_insight': llm_result.get('org_policy_insight', ''),
            'past_project_analysis': llm_result.get('past_project_analysis', ''),
            'year_over_year_improvement': llm_result.get('year_over_year_improvement', ''),
            'competitor_analysis': llm_result.get('competitor_analysis', ''),
            'differentiation_strategy': llm_result.get('differentiation_strategy', ''),
            'risk_factors': llm_result.get('risk_factors', ''),
            'budget_analysis': llm_result.get('budget_analysis', ''),
            'action_items': action_items,
            'proposal_outline': llm_result.get('proposal_outline', ''),
            'overall_recommendation': llm_result.get('overall_recommendation', ''),
            'metadata': {
                'analyzed_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'data_sources': data_sources,
                'analysis_engine': llm_result.get('analysis_source', 'unknown'),
            },
        }

        logger.info("전략 분석 완료")
        return strategy_report

    def generate_batch_strategy(
        self,
        bids: list[dict],
        business_profile: dict,
        rfp_texts: dict[str, str] | None = None,
        past_awards: list[dict] | None = None,
        news_articles: list[dict] | None = None,
    ) -> list[dict]:
        """
        여러 공고에 대해 일괄 전략 분석을 수행합니다.

        Args:
            bids: 공고 목록
            business_profile: 사업자 프로필
            rfp_texts: {공고ID: RFP텍스트} 매핑 (선택)
            past_awards: 과거 낙찰 이력 (선택)
            news_articles: 관련 뉴스 (선택)

        Returns:
            전략 보고서 리스트
        """
        rfp_texts = rfp_texts or {}
        results = []

        for i, bid in enumerate(bids, 1):
            bid_id = bid.get('id', bid.get('bidNtceNo', str(i)))
            rfp_text = rfp_texts.get(bid_id, '')

            logger.info("[%d/%d] 전략 분석 중: %s", i, len(bids), bid.get('title', bid.get('bidNtceNm', '')))

            try:
                strategy = self.generate_strategy(
                    bid=bid,
                    business_profile=business_profile,
                    rfp_text=rfp_text,
                    past_awards=past_awards,
                    news_articles=news_articles,
                )
                results.append(strategy)
            except Exception as e:
                logger.error("전략 분석 실패 (공고 %s): %s", bid_id, e, exc_info=True)
                results.append(self._create_error_report(bid, str(e)))

            # API rate limit 방어
            if i < len(bids):
                time.sleep(self.api_delay)

        return results

    # ══════════════════════════════════════════════
    # 유틸리티 메서드
    # ══════════════════════════════════════════════

    @staticmethod
    def _extract_bid_info(bid: dict) -> dict:
        """공고 dict에서 주요 정보를 정규화하여 추출합니다."""
        return {
            'title': bid.get('title', bid.get('bidNtceNm', '')),
            'organization': bid.get('organization', bid.get('ntceInsttNm', '')),
            'budget': bid.get('budget', bid.get('presmptPrce', '')),
            'deadline': bid.get('deadline', bid.get('bidClseDt', '')),
            'category': bid.get('category', ''),
            'region': bid.get('region', ''),
            'bid_number': bid.get('id', bid.get('bidNtceNo', '')),
        }

    @staticmethod
    def _enrich_action_items(
        action_items: list[str],
        bid: dict,
        business_profile: dict,
    ) -> list[str]:
        """
        행동 체크리스트를 공고/사업자 정보를 기반으로 보강합니다.

        LLM이 생성한 기본 체크리스트에 맥락에 맞는 항목을 추가합니다.
        """
        enriched = list(action_items)  # 원본 보존

        deadline = bid.get('deadline', bid.get('bidClseDt', ''))
        if deadline and '마감일 확인' not in str(action_items):
            enriched.insert(0, f"⏰ 입찰 마감일 확인: {deadline}")

        # 지역 제한 확인
        region = bid.get('region', '')
        biz_region = business_profile.get('region', '')
        if region and region not in ('전국', '제한없음') and biz_region:
            if region != biz_region:
                enriched.append(f"⚠️ 지역 제한 확인 필요: 공고 지역({region}) ≠ 소재지({biz_region})")

        # 필수 면허 확인
        required = bid.get('required_licenses', [])
        held = business_profile.get('licenses', [])
        if required:
            missing = [r for r in required if not any(
                r.upper() in h.upper() or h.upper() in r.upper() for h in held
            )]
            if missing:
                enriched.append(f"🔴 미보유 필수 면허 취득/확보 필요: {', '.join(missing)}")

        return enriched

    @staticmethod
    def _create_error_report(bid: dict, error_msg: str) -> dict:
        """분석 실패 시 에러 보고서를 생성합니다."""
        # 내부 오류 메시지를 사용자에게 노출하지 않도록 필터링
        user_facing_msg = '자동 분석 중 오류가 발생했습니다. 공고 원문을 직접 확인해 주세요.'
        return {
            'bid_info': {
                'title': bid.get('title', bid.get('bidNtceNm', '')),
                'organization': bid.get('organization', bid.get('ntceInsttNm', '')),
                'budget': bid.get('budget', ''),
                'deadline': bid.get('deadline', ''),
                'category': '',
                'region': '',
                'bid_number': bid.get('id', bid.get('bidNtceNo', '')),
            },
            'bid_summary': '분석 실패',
            'competitor_analysis': '',
            'differentiation_strategy': '',
            'risk_factors': user_facing_msg,
            'budget_analysis': '',
            'action_items': ['공고 원문을 직접 확인하세요.'],
            'overall_recommendation': user_facing_msg,
            'metadata': {
                'analyzed_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'data_sources': {},
                'analysis_engine': 'error',
                'error': error_msg,  # 내부 로그용으로만 보존
            },
        }
