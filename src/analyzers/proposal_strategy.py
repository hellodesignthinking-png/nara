"""
제안서 고도화 전략 총괄 분석 모듈

경쟁사 분석, 발주기관 정책, 지역 트렌드, 투찰률 최적화,
RFP 변화 분석을 통합하여 최종 제안서 전략을 생성합니다.

파이프라인 흐름:
  1. DB에서 공고 및 사업자 정보 로드
  2. 경쟁사 수주 패턴 분석 (CompetitorAnalyzer)
  3. 발주기관 정책 방향 분석 (OrgPolicyAnalyzer)
  4. 지역 트렌드 분석 (RegionalTrendAnalyzer)
  5. 투찰률 최적화 (BidRateOptimizer)
  6. RFP 전년 대비 변화 분석 (RFPDiffer)
  7. LLM 최종 전략 보고서 생성 (LLMAnalyzer)
"""

import json
import logging
from datetime import datetime
from typing import Optional

from src.config import load_config
from src.models.database import DatabaseManager
from src.analyzers.competitor_analyzer import CompetitorAnalyzer
from src.analyzers.org_policy_analyzer import OrgPolicyAnalyzer
from src.analyzers.regional_trend_analyzer import RegionalTrendAnalyzer
from src.analyzers.bid_rate_optimizer import BidRateOptimizer
from src.analyzers.rfp_differ import RFPDiffer
from src.analyzers.llm_analyzer import LLMAnalyzer
from src.analyzers.strategy_engine import StrategyEngine

logger = logging.getLogger(__name__)


class ProposalStrategyAnalyzer:
    """
    제안서 고도화 전략 총괄 분석기

    개별 분석 모듈(경쟁사, 정책, 트렌드, 투찰률, RFP 변화)을
    오케스트레이션하여 하나의 통합 전략 보고서를 생성합니다.
    LLM이 사용 가능하면 AI 기반 보고서를, 불가능하면
    구조화된 폴백 보고서를 반환합니다.
    """

    def __init__(self, db: DatabaseManager = None, config=None):
        """
        총괄 분석기를 초기화합니다.

        Args:
            db: DatabaseManager 인스턴스 (None이면 내부에서 생성)
            config: Config 객체 (None이면 load_config()로 로드)
        """
        self.config = config or load_config()
        self.db = db

        # 개별 분석 모듈 초기화
        self.competitor_analyzer = CompetitorAnalyzer()
        self.org_policy_analyzer = OrgPolicyAnalyzer()
        self.regional_analyzer = RegionalTrendAnalyzer()
        self.bid_rate_optimizer = BidRateOptimizer()
        self.rfp_differ = RFPDiffer()

        # LLM 분석기 초기화 (엔진 설정에 따라 Gemini 또는 OpenAI)
        llm_api_key = (
            self.config.gemini_api_key
            if self.config.llm_engine == 'gemini'
            else self.config.openai_api_key
        )
        llm_model = (
            self.config.gemini_model
            if self.config.llm_engine == 'gemini'
            else self.config.openai_model
        )
        self.llm_analyzer = LLMAnalyzer(
            api_key=llm_api_key,
            model=llm_model,
            engine=self.config.llm_engine,
        )

        logger.info("ProposalStrategyAnalyzer 초기화 완료 (LLM 엔진: %s)", self.config.llm_engine)

    def generate_proposal_strategy(self, bid_ntce_no: str, biz_id: str = None) -> dict:
        """
        최종 제안서 고도화 전략 보고서를 생성합니다.

        파이프라인:
        1. DB에서 공고 및 사업자 정보 로드
        2. 경쟁사 수주 패턴 분석
        3. 발주기관 정책 방향 분석
        4. 지역 트렌드 분석
        5. 투찰률 최적화
        6. RFP 전년 대비 변화 분석
        7. LLM 최종 전략 보고서 생성

        Args:
            bid_ntce_no: 입찰공고번호
            biz_id: 사업자등록번호 (None이면 DB의 첫 번째 사업자 사용)

        Returns:
            통합 전략 보고서 dict:
            - bid_info: 공고 기본 정보
            - business_profile: 사업자 프로필 요약
            - competitor_analysis: 경쟁사 수주 패턴 분석 결과
            - org_policy: 발주기관 정책 방향 분석 결과
            - regional_trend: 지역 트렌드 분석 결과
            - bid_rate_optimization: 투찰률 최적화 결과
            - rfp_changes: RFP 전년 대비 변화 분석 결과
            - llm_strategy_report: LLM 생성 최종 전략 보고서
            - metadata: 분석 메타 정보
        """
        logger.info("═══ 제안서 고도화 전략 분석 시작: 공고번호 %s ═══", bid_ntce_no)
        analysis_start_time = datetime.now()

        # ── 0단계: DB 연결 확보 ──
        db = self.db
        if db is None:
            db = DatabaseManager()
            db.connect()
            logger.debug("내부 DatabaseManager 생성 및 연결 완료")

        # ── 1단계: 공고 정보 로드 ──
        bid_obj = db.get_bid_by_no(bid_ntce_no)
        if bid_obj is None:
            logger.error("공고번호 %s에 해당하는 공고를 찾을 수 없습니다.", bid_ntce_no)
            return {
                'error': f'공고번호 {bid_ntce_no}에 해당하는 공고를 찾을 수 없습니다.',
                'bid_ntce_no': bid_ntce_no,
            }

        bid = bid_obj.to_dict()
        bid_title = bid.get('title', '')
        org_name = bid.get('org_name', '')
        rfp_text = bid.get('rfp_text', '') or ''
        region = bid.get('region', '')

        logger.info("공고 로드 완료: %s (%s)", bid_title, org_name)

        # ── 1-1단계: 사업자 프로필 로드 ──
        business_profile = {}
        if biz_id:
            biz_obj = db.get_business(biz_id)
            if biz_obj:
                business_profile = biz_obj.to_dict()
                logger.info("사업자 프로필 로드 완료: %s", business_profile.get('company_name', ''))
            else:
                logger.warning("사업자 ID %s에 해당하는 프로필을 찾을 수 없습니다.", biz_id)
        else:
            # biz_id 미지정 시 DB의 첫 번째 사업자 사용
            businesses = db.get_businesses()
            if businesses:
                business_profile = businesses[0].to_dict()
                biz_id = business_profile.get('biz_id', '')
                logger.info("기본 사업자 프로필 사용: %s", business_profile.get('company_name', ''))
            else:
                logger.warning("등록된 사업자 프로필이 없습니다. 빈 프로필로 진행합니다.")

        # ── 2단계: 경쟁사 수주 패턴 분석 ──
        competitor_data = {}
        try:
            competitor_result = self.competitor_analyzer.find_competitors_for_bid(
                db=db,
                bid_dict=bid,
            )
            competitor_data = competitor_result.get('competitors', {})
            logger.info("경쟁사 분석 완료: %d건의 경쟁사 데이터 수집",
                         len(competitor_data.get('top_competitors', [])))
        except Exception as e:
            logger.warning("경쟁사 분석 실패 (계속 진행): %s", e)
            competitor_data = {'error': str(e), 'top_competitors': []}

        # ── 3단계: 발주기관 정책 방향 분석 ──
        org_policy = {}
        try:
            org_policy = self.org_policy_analyzer.analyze_org_policy(
                db=db,
                org_name=org_name,
            )
            logger.info("발주기관 정책 분석 완료: %s", org_name)
        except Exception as e:
            logger.warning("발주기관 정책 분석 실패 (계속 진행): %s", e)
            org_policy = {'error': str(e)}

        # ── 4단계: 지역 트렌드 분석 ──
        regional_trend = {}
        try:
            regional_trend = self.regional_analyzer.analyze_regional_trend(
                db=db,
                region=region or '전국',
            )
            # 정책 부합도도 추가 계산
            policy_alignment = self.regional_analyzer.calculate_policy_alignment(
                bid=bid, region=region or '전국',
            )
            regional_trend['policy_alignment'] = policy_alignment
            logger.info("지역 트렌드 분석 완료: %s", region or '전국')
        except Exception as e:
            logger.warning("지역 트렌드 분석 실패 (계속 진행): %s", e)
            regional_trend = {'error': str(e)}

        # ── 5단계: 투찰률 최적화 ──
        bid_rate_result = {}
        try:
            bid_rate_result = self.bid_rate_optimizer.optimize_bid_rate(
                db=db,
                bid=bid,
            )
            recommended = bid_rate_result.get('recommended_rate', {})
            logger.info("투찰률 최적화 완료: 추천 투찰률 %s%%",
                         recommended.get('optimal', 'N/A'))
        except Exception as e:
            logger.warning("투찰률 최적화 실패 (계속 진행): %s", e)
            bid_rate_result = {'error': str(e)}

        # ── 6단계: RFP 전년 대비 변화 분석 ──
        rfp_changes = {}
        try:
            # 유사한 과거 입찰 검색
            past_bid = self.rfp_differ.find_similar_past_bid(
                current_bid={'title': bid_title, 'bid_ntce_no': bid_ntce_no},
                db_manager=db,
            )

            if past_bid:
                # 과거 공고의 RFP 텍스트 로드
                past_bid_obj = db.get_bid_by_no(past_bid.get('bid_ntce_no', ''))
                past_rfp_text = ''
                if past_bid_obj:
                    past_rfp_text = past_bid_obj.rfp_text or ''

                if rfp_text and past_rfp_text:
                    diff_result = self.rfp_differ.compute_diff(past_rfp_text, rfp_text)
                    key_changes = self.rfp_differ.extract_key_changes(past_rfp_text, rfp_text)
                    rfp_changes = {
                        'past_bid': past_bid,
                        'diff_summary': {
                            'similarity_ratio': diff_result.get('similarity_ratio', 0),
                            'changed_count': diff_result.get('changed_count', 0),
                            'added_count': len(diff_result.get('added_lines', [])),
                            'removed_count': len(diff_result.get('removed_lines', [])),
                        },
                        'key_changes': key_changes[:20],  # 최대 20건
                    }
                    logger.info("RFP 변화 분석 완료: 유사도 %.1f%%, 변경 %d건",
                                 diff_result.get('similarity_ratio', 0) * 100,
                                 diff_result.get('changed_count', 0))
                else:
                    rfp_changes = {
                        'past_bid': past_bid,
                        'note': 'RFP 텍스트가 없어 상세 비교가 불가합니다.',
                    }
            else:
                rfp_changes = {'note': '유사한 과거 입찰을 찾지 못했습니다.'}
                logger.info("유사 과거 입찰 없음 — RFP 변화 분석 건너뜀")
        except Exception as e:
            logger.warning("RFP 변화 분석 실패 (계속 진행): %s", e)
            rfp_changes = {'error': str(e)}

        # ── 6-1단계: 과거 낙찰 이력 수집 ──
        past_awards = []
        try:
            award_objs = db.get_awards_by_title(bid_title, limit=20)
            past_awards = [a.to_dict() for a in award_objs]
            logger.info("과거 낙찰 이력 수집: %d건", len(past_awards))
        except Exception as e:
            logger.warning("과거 낙찰 이력 수집 실패: %s", e)

        # ── 7단계: 구조화된 분석 결과 통합 ──
        enhanced_analysis = {
            'competitor_data': competitor_data,
            'org_policy': org_policy,
            'regional_trend': regional_trend,
            'bid_rate_optimization': bid_rate_result,
            'rfp_changes': rfp_changes,
            'past_awards': past_awards,
        }

        # ── 8단계: LLM 최종 전략 보고서 생성 ──
        llm_strategy_report = {}
        try:
            llm_strategy_report = self.llm_analyzer.generate_enhanced_strategy(
                bid=bid,
                business_profile=business_profile,
                structured_analysis=enhanced_analysis,
            )
            logger.info("LLM 최종 전략 보고서 생성 완료 (소스: %s)",
                         llm_strategy_report.get('analysis_source', 'unknown'))
        except Exception as e:
            logger.warning("LLM 전략 보고서 생성 실패 — 폴백 보고서 사용: %s", e)
            llm_strategy_report = self._build_fallback_report(
                bid=bid,
                business_profile=business_profile,
                enhanced_analysis=enhanced_analysis,
            )

        # ── 9단계: 최종 통합 보고서 조립 ──
        analysis_duration = (datetime.now() - analysis_start_time).total_seconds()

        final_report = {
            'bid_info': {
                'bid_ntce_no': bid.get('bid_ntce_no', ''),
                'title': bid_title,
                'org_name': org_name,
                'budget': bid.get('budget'),
                'bid_close_dt': bid.get('bid_close_dt', ''),
                'category': bid.get('category', ''),
                'region': region,
                'contract_method': bid.get('contract_method', ''),
            },
            'business_profile': {
                'biz_id': business_profile.get('biz_id', ''),
                'company_name': business_profile.get('company_name', ''),
                'licenses': business_profile.get('licenses', '[]'),
                'regions': business_profile.get('regions', '[]'),
            },
            'competitor_analysis': competitor_data,
            'org_policy': org_policy,
            'regional_trend': regional_trend,
            'bid_rate_optimization': bid_rate_result,
            'rfp_changes': rfp_changes,
            'llm_strategy_report': llm_strategy_report,
            'metadata': {
                'analyzed_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'analysis_duration_seconds': round(analysis_duration, 2),
                'llm_engine': self.config.llm_engine,
                'llm_available': self.llm_analyzer.is_available,
                'data_sources': {
                    'rfp_available': bool(rfp_text),
                    'rfp_length': len(rfp_text),
                    'past_awards_count': len(past_awards),
                    'competitor_count': len(competitor_data.get('top_competitors', competitor_data.get('competitors', []))),
                    'rfp_changes_available': bool(rfp_changes.get('key_changes')),
                    'business_profile_available': bool(business_profile),
                },
            },
        }

        logger.info(
            "═══ 제안서 고도화 전략 분석 완료: %s (소요시간: %.1f초) ═══",
            bid_title, analysis_duration,
        )
        return final_report

    def _build_fallback_report(
        self,
        bid: dict,
        business_profile: dict,
        enhanced_analysis: dict,
    ) -> dict:
        """
        LLM 사용 불가 시 구조화된 폴백 전략 보고서를 생성합니다.

        개별 분석 모듈의 결과를 조합하여 사람이 읽을 수 있는
        형태의 보고서를 구성합니다.

        Args:
            bid: 공고 정보 dict
            business_profile: 사업자 프로필 dict
            enhanced_analysis: 개별 분석 결과가 통합된 dict

        Returns:
            폴백 전략 보고서 dict
        """
        bid_title = bid.get('title', '정보 없음')
        org_name = bid.get('org_name', '정보 없음')
        budget = bid.get('budget', '정보 없음')
        biz_name = business_profile.get('company_name', '미지정')

        # 경쟁사 정보 요약
        competitor_data = enhanced_analysis.get('competitor_data', {})
        competitors = competitor_data.get('top_competitors', competitor_data.get('competitors', []))
        competitor_summary = '경쟁사 데이터 없음'
        if competitors:
            top_competitors = competitors[:5]
            comp_lines = []
            for c in top_competitors:
                name = c.get('name', c.get('winner_name', c.get('company_name', '')))
                count = c.get('win_count', c.get('award_count', 0))
                comp_lines.append(f"- {name}: 수주 {count}건")
            competitor_summary = '\n'.join(comp_lines)

        # 투찰률 최적화 요약
        bid_rate = enhanced_analysis.get('bid_rate_optimization', {})
        rate_summary = '투찰률 분석 데이터 없음'
        if bid_rate and not bid_rate.get('error'):
            recommended = bid_rate.get('recommended_rate', 'N/A')
            min_rate = bid_rate.get('min_rate', 'N/A')
            max_rate = bid_rate.get('max_rate', 'N/A')
            rate_summary = f"추천 투찰률: {recommended}% (범위: {min_rate}%~{max_rate}%)"

        # RFP 변화 요약
        rfp_changes = enhanced_analysis.get('rfp_changes', {})
        rfp_summary = rfp_changes.get('note', '')
        if rfp_changes.get('diff_summary'):
            diff = rfp_changes['diff_summary']
            rfp_summary = (
                f"전년 대비 유사도 {diff.get('similarity_ratio', 0) * 100:.1f}%, "
                f"변경사항 {diff.get('changed_count', 0)}건 "
                f"(추가 {diff.get('added_count', 0)}, 삭제 {diff.get('removed_count', 0)})"
            )

        # 발주기관 정책 요약
        org_policy = enhanced_analysis.get('org_policy', {})
        policy_summary = org_policy.get('summary', '발주기관 정책 분석 데이터 없음')
        if org_policy.get('error'):
            policy_summary = '발주기관 정책 분석을 수행할 수 없습니다.'

        # 지역 트렌드 요약
        regional = enhanced_analysis.get('regional_trend', {})
        regional_summary = regional.get('summary', '지역 트렌드 데이터 없음')
        if regional.get('error'):
            regional_summary = '지역 트렌드 분석을 수행할 수 없습니다.'

        # 행동 체크리스트 생성
        action_items = [
            f"⏰ 입찰 마감일 확인: {bid.get('bid_close_dt', '확인 필요')}",
            '📋 공고 원문 및 첨부파일 다운로드',
            '📝 제안요청서(RFP) 상세 검토',
            '✅ 참가 자격 요건 확인',
            '📜 필수 면허/자격 보유 여부 점검',
            '📊 유사 사업 실적 증빙 자료 준비',
            '📅 제안서 작성 일정 수립',
            '🏗️ 현장설명회 참석 여부 확인',
        ]

        # 과거 수주 이력에서 주의사항 추가
        past_awards = enhanced_analysis.get('past_awards', [])
        if past_awards:
            recent_winner = past_awards[0].get('winner_name', '')
            if recent_winner:
                action_items.append(
                    f"🔍 전년도 수주업체({recent_winner}) 수행 결과 조사"
                )

        return {
            'bid_summary': (
                f"'{bid_title}' 사업은 {org_name}에서 발주한 공고입니다. "
                f"추정가격은 {budget}원이며, {biz_name}의 역량을 바탕으로 "
                f"참여 전략을 수립할 필요가 있습니다."
            ),
            'competitor_analysis': competitor_summary,
            'org_policy_insight': policy_summary,
            'regional_trend': regional_summary,
            'differentiation_strategy': (
                f"'{biz_name}'의 핵심 역량을 바탕으로 한 차별화 전략을 수립하세요. "
                f"AI 분석 활성화 시 구체적인 전략이 제공됩니다."
            ),
            'risk_factors': '공고 원문을 직접 확인하여 자격 제한, 지역 제한 등을 검토하세요.',
            'budget_analysis': rate_summary,
            'rfp_change_analysis': rfp_summary,
            'action_items': action_items,
            'proposal_outline': (
                '1) 배경 및 목적 (발주처 정책 방향과 사업 연계성)\n'
                '2) 전년도 사업 분석 및 차별화 포인트\n'
                '3) 기술 방법론 및 추진 전략\n'
                '4) 추진 체계 및 프로젝트 관리 방안\n'
                '5) 기대효과 및 성과지표(KPI)'
            ),
            'overall_recommendation': (
                'AI 분석이 비활성화되어 자동 전략 수립이 제한됩니다. '
                'GEMINI_API_KEY 또는 OPENAI_API_KEY를 설정하면 '
                '경쟁사·정책·트렌드를 종합한 고도화된 전략 보고서가 생성됩니다.'
            ),
            'analysis_source': 'fallback',
        }
