"""
투찰률 최적화 모듈

과거 낙찰 데이터의 투찰률(bid_rate)을 분석하여
최적 투찰률 범위를 제안합니다.
"""

import logging
import math
from collections import defaultdict
from typing import Optional

logger = logging.getLogger(__name__)


class BidRateOptimizer:
    """
    과거 낙찰 데이터의 투찰률을 분석하여 최적 투찰률을 제안합니다.
    """

    # 계약방식별 기본 투찰률 범위 (데이터 부족 시 폴백)
    DEFAULT_RATES = {
        "협상에 의한 계약": {"optimal": 90.0, "low": 87.0, "high": 93.0},
        "적격심사": {"optimal": 87.5, "low": 85.0, "high": 90.0},
        "최저가": {"optimal": 85.0, "low": 82.0, "high": 88.0},
    }

    # 예산 규모별 카테고리
    BUDGET_CATEGORIES = [
        (100_000_000, "1억 미만"),
        (500_000_000, "1억~5억"),
        (1_000_000_000, "5억~10억"),
        (5_000_000_000, "10억~50억"),
        (float("inf"), "50억 이상"),
    ]

    def optimize_bid_rate(self, db, bid: dict) -> dict:
        """
        최적 투찰률을 제안합니다.

        분석 순서:
        1. 유사 키워드 기반 통계
        2. 발주기관 기반 통계
        3. 계약방식별 기본값 폴백

        Args:
            db: DatabaseManager 인스턴스
            bid: 공고 정보 dict

        Returns:
            투찰률 최적화 결과 딕셔너리
        """
        logger.info("투찰률 최적화 분석 시작: %s", bid.get("title", "")[:30])

        title = bid.get("title", "")
        org_name = bid.get("org_name", "")
        budget = bid.get("budget", 0)
        contract_method = bid.get("contract_method", "")

        # 1. 유사 키워드 기반 통계
        keyword_stats = {}
        if title:
            import re
            # 2글자 이상의 한글/영문 단어 추출
            words = re.findall(r'[가-힣]{2,}|[A-Za-z]{2,}', title)
            # 연도나 불필요한 조달 수식어 필터링
            stopwords = {"2020년", "2021년", "2022년", "2023년", "2024년", "2025년", "2026년", "2027년", "긴급", "공고", "재공고", "입찰", "사업", "용역", "구축", "개발"}
            valid_keywords = [w for w in words if w not in stopwords]
            
            # 유효 키워드 중 첫 번째 키워드를 사용 (없으면 첫 번째 추출어 폴백)
            keyword = valid_keywords[0] if valid_keywords else (words[0] if words else "")
            
            if keyword and len(keyword) >= 2:
                try:
                    keyword_stats = db.get_award_stats(keyword=keyword)
                except Exception as e:
                    logger.warning("키워드 기반 투찰률 통계 조회 실패 (키워드: %s): %s", keyword, e)

        # 2. 발주기관 기반 통계
        org_stats = {}
        if org_name:
            try:
                org_stats = db.get_award_stats(org_name=org_name)
            except Exception as e:
                logger.warning("기관 기반 투찰률 통계 조회 실패: %s", e)

        # 3. 최적 투찰률 결정
        recommended = self._calculate_optimal_rate(
            keyword_stats, org_stats, contract_method, budget
        )

        # 4. 위험도 평가
        risk_assessment = self._generate_risk_assessment(
            recommended["optimal"], contract_method
        )

        # 5. 예산 구간별 분석
        budget_category = self._get_budget_category(budget)

        return {
            "recommended_rate": recommended,
            "analysis_basis": {
                "keyword_stats": keyword_stats if keyword_stats.get("total_count", 0) > 0 else None,
                "org_stats": org_stats if org_stats.get("total_count", 0) > 0 else None,
                "data_source": self._get_data_source(keyword_stats, org_stats),
            },
            "by_org": {
                "org_name": org_name,
                "org_avg_rate": org_stats.get("avg_bid_rate", 0),
                "org_data_count": org_stats.get("total_count", 0),
            },
            "by_budget_range": {
                "budget_category": budget_category,
                "budget": budget,
            },
            "risk_assessment": risk_assessment,
        }

    def _calculate_optimal_rate(
        self,
        keyword_stats: dict,
        org_stats: dict,
        contract_method: str,
        budget: int,
    ) -> dict:
        """데이터를 종합하여 최적 투찰률을 계산합니다."""

        kw_count = keyword_stats.get("total_count", 0)
        org_count = org_stats.get("total_count", 0)

        # 데이터 충분성에 따라 가중 평균
        if kw_count >= 10 and org_count >= 5:
            # 키워드 데이터가 더 관련성 높으므로 60:40 가중
            kw_avg = keyword_stats.get("avg_bid_rate", 0)
            org_avg = org_stats.get("avg_bid_rate", 0)
            optimal = kw_avg * 0.6 + org_avg * 0.4
            confidence = min(0.95, 0.5 + (kw_count + org_count) / 200)
            std_estimate = abs(keyword_stats.get("max_bid_rate", 0) - keyword_stats.get("min_bid_rate", 0)) / 4

        elif kw_count >= 5:
            optimal = keyword_stats.get("median_bid_rate", 0) or keyword_stats.get("avg_bid_rate", 0)
            confidence = min(0.8, 0.3 + kw_count / 50)
            std_estimate = abs(keyword_stats.get("max_bid_rate", 0) - keyword_stats.get("min_bid_rate", 0)) / 4

        elif org_count >= 5:
            optimal = org_stats.get("median_bid_rate", 0) or org_stats.get("avg_bid_rate", 0)
            confidence = min(0.7, 0.3 + org_count / 50)
            std_estimate = abs(org_stats.get("max_bid_rate", 0) - org_stats.get("min_bid_rate", 0)) / 4

        elif kw_count > 0 or org_count > 0:
            stats = keyword_stats if kw_count > 0 else org_stats
            optimal = stats.get("avg_bid_rate", 0)
            confidence = 0.3
            std_estimate = 3.0

        else:
            # 폴백: 계약방식별 기본값
            defaults = self._get_default_for_contract(contract_method)
            return {
                "optimal": defaults["optimal"],
                "range_low": defaults["low"],
                "range_high": defaults["high"],
                "confidence": 0.15,
                "source": "기본값 (데이터 부족)",
            }

        # 범위 계산 (표준편차 기반)
        std_estimate = max(std_estimate, 1.5)
        range_low = round(max(optimal - std_estimate, 75.0), 1)
        range_high = round(min(optimal + std_estimate, 99.0), 1)

        return {
            "optimal": round(optimal, 1),
            "range_low": range_low,
            "range_high": range_high,
            "confidence": round(confidence, 2),
            "source": "과거 데이터 분석",
        }

    def _generate_risk_assessment(self, optimal_rate: float, contract_method: str) -> dict:
        """위험도 평가를 생성합니다."""
        if not optimal_rate or optimal_rate <= 0:
            return {
                "too_low_risk": "데이터 부족으로 평가 불가",
                "too_high_risk": "데이터 부족으로 평가 불가",
                "strategy": "유사 사업 낙찰 현황을 직접 확인하세요.",
            }

        low_threshold = optimal_rate - 5
        high_threshold = optimal_rate + 3

        # 계약방식별 전략
        if "협상" in contract_method:
            strategy = (
                f"협상에 의한 계약이므로 기술 점수가 핵심입니다. "
                f"투찰률 {optimal_rate - 2:.0f}~{optimal_rate + 1:.0f}% 범위에서 "
                f"기술 제안 품질에 집중하세요."
            )
        elif "적격" in contract_method:
            strategy = (
                f"적격심사 방식이므로 가격과 기술의 균형이 중요합니다. "
                f"투찰률 {optimal_rate - 1:.0f}~{optimal_rate + 1:.0f}% 범위를 권장합니다."
            )
        elif "최저" in contract_method:
            strategy = (
                f"최저가 방식이므로 가격 경쟁력이 최우선입니다. "
                f"투찰률 {optimal_rate - 2:.0f}~{optimal_rate:.0f}% 범위에서 공격적으로 제안하세요."
            )
        else:
            strategy = (
                f"투찰률 {optimal_rate - 2:.0f}~{optimal_rate + 2:.0f}% 범위를 권장합니다. "
                f"계약방식에 따라 기술/가격 비중을 조정하세요."
            )

        return {
            "too_low_risk": f"{low_threshold:.0f}% 미만 시 가격 덤핑으로 심사 감점 또는 부정당업체 제재 우려",
            "too_high_risk": f"{high_threshold:.0f}% 초과 시 가격 경쟁력 부족으로 탈락 위험 증가",
            "strategy": strategy,
        }

    def _get_default_for_contract(self, contract_method: str) -> dict:
        """계약방식에 맞는 기본 투찰률을 반환합니다."""
        for method, rates in self.DEFAULT_RATES.items():
            if method in (contract_method or ""):
                return rates
        # 일반적 기본값
        return {"optimal": 88.0, "low": 85.0, "high": 91.0}

    def _get_budget_category(self, budget: int) -> str:
        """예산 규모 카테고리를 분류합니다."""
        if not budget:
            return "미공개"
        for threshold, label in self.BUDGET_CATEGORIES:
            if budget < threshold:
                return label
        return "50억 이상"

    def _get_data_source(self, keyword_stats: dict, org_stats: dict) -> str:
        """데이터 소스 설명을 생성합니다."""
        kw_count = keyword_stats.get("total_count", 0)
        org_count = org_stats.get("total_count", 0)

        if kw_count >= 10 and org_count >= 5:
            return f"유사 사업 {kw_count}건 + 발주기관 {org_count}건 데이터 기반"
        elif kw_count >= 5:
            return f"유사 사업 {kw_count}건 데이터 기반"
        elif org_count >= 5:
            return f"발주기관 {org_count}건 데이터 기반"
        elif kw_count > 0 or org_count > 0:
            return f"제한된 데이터 ({kw_count + org_count}건) 기반 — 참고용"
        else:
            return "데이터 부족 — 기본값 사용"
