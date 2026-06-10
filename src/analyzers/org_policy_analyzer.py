"""
발주기관 정책 분석 모듈

발주기관의 입찰 패턴, 예산 추이, 주력 분야, 선호 업체 등을
분석하여 입찰 전략 수립에 활용합니다.
반복 사업 탐지 및 수요기관 분석 기능도 제공합니다.
"""

import logging
import re
from collections import Counter, defaultdict
from typing import Optional

from src.models.database import DatabaseManager
from src.models.schemas import AwardInfo, BidAnnouncement

logger = logging.getLogger(__name__)


class OrgPolicyAnalyzer:
    """
    발주기관 정책 분석 클래스

    발주기관의 과거 공고 및 낙찰 데이터를 기반으로
    기관의 발주 패턴, 예산 변화, 주력 분야, 선호 업체를 분석합니다.
    """

    def analyze_org_policy(
        self,
        db: DatabaseManager,
        org_name: str,
    ) -> dict:
        """
        발주기관의 정책 방향을 종합 분석합니다.

        기관의 과거 공고 이력과 낙찰 이력을 수집하여
        카테고리별 분포, 예산 추이, 선호 업체, 입찰 특성을 분석합니다.

        Args:
            db: DatabaseManager 인스턴스
            org_name: 발주기관명

        Returns:
            {
                "org_name": 기관명,
                "total_bids": 총 공고 건수,
                "total_awards": 총 낙찰 건수,
                "top_categories": [  # 주력 분야 (상위 10개)
                    {"category": 분야명, "count": 건수, "share": 비율(%)}, ...
                ],
                "budget_trends": {  # 연도별 예산 추이
                    "2024": {"count": 건수, "total_budget": 합계, "avg_budget": 평균}, ...
                },
                "preferred_vendors": [  # 선호 업체 (낙찰 횟수 기준 상위 10개)
                    {"name": 업체명, "win_count": 낙찰횟수, "total_amount": 합계금액}, ...
                ],
                "bid_characteristics": {  # 입찰 특성
                    "common_bid_methods": [입찰방식 분포],
                    "common_contract_methods": [계약방법 분포],
                    "avg_budget": 평균 예산,
                    "region_distribution": [지역 분포],
                },
                "award_stats": {  # 낙찰 통계
                    "avg_bid_rate": 평균 투찰률,
                    "avg_award_amount": 평균 낙찰금액,
                },
            }
        """
        logger.info("발주기관 정책 분석 시작: %s", org_name)

        # 데이터 수집
        bids = db.get_bids_by_org(org_name, limit=500)
        awards = db.get_awards_by_org(org_name, limit=500)

        if not bids and not awards:
            logger.info("발주기관 데이터 없음: %s", org_name)
            return self._empty_org_result(org_name)

        result = {
            "org_name": org_name,
            "total_bids": len(bids),
            "total_awards": len(awards),
            "top_categories": self._analyze_categories(bids),
            "budget_trends": self._analyze_budget_trends(bids),
            "preferred_vendors": self._analyze_preferred_vendors(awards),
            "bid_characteristics": self._analyze_bid_characteristics(bids),
            "award_stats": self._analyze_award_stats(awards),
        }

        logger.info(
            "발주기관 정책 분석 완료: %s (공고 %d건, 낙찰 %d건)",
            org_name, len(bids), len(awards),
        )
        return result

    def find_recurring_project(
        self,
        db: DatabaseManager,
        bid_dict: dict,
    ) -> dict:
        """
        현재 공고가 반복 사업인지 확인합니다.

        공고 제목의 핵심 키워드로 과거 유사 공고를 검색하고,
        동일/유사 사업이 반복 발주된 이력을 분석합니다.

        Args:
            db: DatabaseManager 인스턴스
            bid_dict: 현재 입찰공고 정보 딕셔너리
                - title (str): 공고명
                - org_name (str, optional): 발주기관명

        Returns:
            {
                "is_recurring": 반복사업 여부 (bool),
                "confidence": 확신도 ("높음" | "보통" | "낮음"),
                "past_occurrences": [  # 과거 발주 이력
                    {
                        "title": 공고명,
                        "org_name": 발주기관,
                        "budget": 예산,
                        "collected_at": 수집일시,
                    }, ...
                ],
                "budget_history": [  # 예산 변화 추이
                    {"year": 연도, "budget": 예산}, ...
                ],
                "pattern_summary": 반복 패턴 요약 문자열,
            }
        """
        title = bid_dict.get("title", "")
        org_name = bid_dict.get("org_name", "")

        if not title:
            logger.warning("공고 제목이 비어있어 반복사업 분석을 건너뜁니다.")
            return {
                "is_recurring": False,
                "confidence": "낮음",
                "past_occurrences": [],
                "budget_history": [],
                "pattern_summary": "분석 불가 (공고 제목 없음)",
            }

        logger.info("반복사업 분석 시작: %s", title)

        # 유사 공고 검색
        similar_bids = db.get_similar_bids_by_title(title, limit=50)

        if not similar_bids:
            return {
                "is_recurring": False,
                "confidence": "낮음",
                "past_occurrences": [],
                "budget_history": [],
                "pattern_summary": "과거 유사 공고를 찾을 수 없습니다.",
            }

        # 제목 유사도 기반 필터링
        relevant_bids = self._filter_relevant_bids(title, similar_bids, org_name)

        if not relevant_bids:
            return {
                "is_recurring": False,
                "confidence": "낮음",
                "past_occurrences": [
                    {
                        "title": b.title,
                        "org_name": b.org_name,
                        "budget": b.budget,
                        "collected_at": b.collected_at.strftime("%Y-%m-%d") if b.collected_at else None,
                    }
                    for b in similar_bids[:5]
                ],
                "budget_history": [],
                "pattern_summary": "유사 공고가 있으나 동일 사업으로 판단하기 어렵습니다.",
            }

        # 과거 발주 이력 정리
        past_occurrences = [
            {
                "title": b.title,
                "org_name": b.org_name,
                "budget": b.budget,
                "collected_at": b.collected_at.strftime("%Y-%m-%d") if b.collected_at else None,
            }
            for b in relevant_bids
        ]

        # 예산 변화 추이
        budget_history = []
        for b in sorted(relevant_bids, key=lambda x: x.collected_at or ""):
            if b.budget and b.collected_at:
                budget_history.append({
                    "year": b.collected_at.strftime("%Y"),
                    "budget": b.budget,
                })

        # 확신도 판단
        occurrence_count = len(relevant_bids)
        same_org_count = sum(
            1 for b in relevant_bids
            if b.org_name and org_name and org_name in b.org_name
        )

        if same_org_count >= 2:
            confidence = "높음"
        elif occurrence_count >= 3:
            confidence = "보통"
        else:
            confidence = "낮음"

        # 패턴 요약 생성
        pattern_summary = self._generate_recurring_summary(
            relevant_bids, budget_history, org_name,
        )

        result = {
            "is_recurring": occurrence_count >= 2,
            "confidence": confidence,
            "past_occurrences": past_occurrences,
            "budget_history": budget_history,
            "pattern_summary": pattern_summary,
        }

        logger.info(
            "반복사업 분석 완료: %s (반복: %s, 확신도: %s, 과거 %d건)",
            title, result["is_recurring"], confidence, occurrence_count,
        )
        return result

    def analyze_demand_org(
        self,
        db: DatabaseManager,
        demand_org_name: str,
    ) -> dict:
        """
        수요기관을 분석합니다.

        수요기관(실제 사업을 필요로 하는 기관)의 과거 발주 이력,
        주력 분야, 예산 규모를 분석합니다.

        Args:
            db: DatabaseManager 인스턴스
            demand_org_name: 수요기관명

        Returns:
            {
                "demand_org_name": 수요기관명,
                "total_bids": 총 공고 건수,
                "top_categories": [카테고리별 분포],
                "budget_stats": {  # 예산 통계
                    "avg": 평균, "min": 최소, "max": 최대, "total": 합계,
                },
                "recent_bids": [  # 최근 5건 공고
                    {"title": 공고명, "budget": 예산, "date": 날짜}, ...
                ],
                "bid_method_distribution": [입찰방식 분포],
            }
        """
        logger.info("수요기관 분석 시작: %s", demand_org_name)

        # 수요기관명으로 공고 검색 (demand_org_name 필드 기준)
        bids = db.search_bids(keyword=None, org_name=None, limit=500)
        # demand_org_name으로 필터링
        demand_bids = [
            b for b in bids
            if b.demand_org_name and demand_org_name in b.demand_org_name
        ]

        if not demand_bids:
            # org_name으로도 시도
            demand_bids_by_org = db.get_bids_by_org(demand_org_name, limit=200)
            demand_bids = demand_bids_by_org

        if not demand_bids:
            logger.info("수요기관 데이터 없음: %s", demand_org_name)
            return {
                "demand_org_name": demand_org_name,
                "total_bids": 0,
                "top_categories": [],
                "budget_stats": {},
                "recent_bids": [],
                "bid_method_distribution": [],
            }

        # 카테고리 분석
        top_categories = self._analyze_categories(demand_bids)

        # 예산 통계
        budgets = [b.budget for b in demand_bids if b.budget and b.budget > 0]
        budget_stats = {}
        if budgets:
            budget_stats = {
                "avg": int(sum(budgets) / len(budgets)),
                "min": min(budgets),
                "max": max(budgets),
                "total": sum(budgets),
            }

        # 최근 공고
        sorted_bids = sorted(
            demand_bids,
            key=lambda b: b.collected_at or "",
            reverse=True,
        )
        recent_bids = [
            {
                "title": b.title,
                "budget": b.budget,
                "date": b.collected_at.strftime("%Y-%m-%d") if b.collected_at else None,
            }
            for b in sorted_bids[:5]
        ]

        # 입찰방식 분포
        bid_method_counter: Counter = Counter()
        for b in demand_bids:
            if b.bid_method:
                bid_method_counter[b.bid_method] += 1
        bid_method_distribution = [
            {"method": method, "count": cnt}
            for method, cnt in bid_method_counter.most_common(5)
        ]

        result = {
            "demand_org_name": demand_org_name,
            "total_bids": len(demand_bids),
            "top_categories": top_categories,
            "budget_stats": budget_stats,
            "recent_bids": recent_bids,
            "bid_method_distribution": bid_method_distribution,
        }

        logger.info(
            "수요기관 분석 완료: %s (공고 %d건)",
            demand_org_name, len(demand_bids),
        )
        return result

    # ══════════════════════════════════════════════
    # 내부 분석 헬퍼 메서드
    # ══════════════════════════════════════════════

    @staticmethod
    def _analyze_categories(bids: list[BidAnnouncement]) -> list[dict]:
        """공고 목록에서 카테고리별 분포를 분석합니다."""
        category_counter: Counter = Counter()
        for bid in bids:
            category = bid.category or "미분류"
            category_counter[category] += 1

        total = len(bids) if bids else 1
        return [
            {
                "category": cat,
                "count": cnt,
                "share": round(cnt / total * 100, 1),
            }
            for cat, cnt in category_counter.most_common(10)
        ]

    @staticmethod
    def _analyze_budget_trends(bids: list[BidAnnouncement]) -> dict:
        """공고 목록에서 연도별 예산 추이를 분석합니다."""
        yearly_data: dict[str, dict] = defaultdict(
            lambda: {"count": 0, "total_budget": 0, "budgets": []}
        )

        for bid in bids:
            if bid.collected_at:
                year = bid.collected_at.strftime("%Y")
                yearly_data[year]["count"] += 1
                if bid.budget and bid.budget > 0:
                    yearly_data[year]["total_budget"] += bid.budget
                    yearly_data[year]["budgets"].append(bid.budget)

        # 평균 계산 및 budgets 리스트 제거
        result = {}
        for year in sorted(yearly_data.keys()):
            data = yearly_data[year]
            budgets = data.pop("budgets")
            data["avg_budget"] = int(sum(budgets) / len(budgets)) if budgets else 0
            result[year] = data

        return result

    @staticmethod
    def _analyze_preferred_vendors(awards: list[AwardInfo]) -> list[dict]:
        """낙찰 이력에서 선호 업체를 분석합니다."""
        vendor_data: dict[str, dict] = defaultdict(
            lambda: {"win_count": 0, "total_amount": 0}
        )

        for award in awards:
            if award.winner_name:
                vendor_data[award.winner_name]["win_count"] += 1
                if award.award_amount:
                    vendor_data[award.winner_name]["total_amount"] += award.award_amount

        # 낙찰 횟수 기준 상위 10개
        sorted_vendors = sorted(
            vendor_data.items(),
            key=lambda x: x[1]["win_count"],
            reverse=True,
        )

        return [
            {
                "name": name,
                "win_count": data["win_count"],
                "total_amount": data["total_amount"],
            }
            for name, data in sorted_vendors[:10]
        ]

    @staticmethod
    def _analyze_bid_characteristics(bids: list[BidAnnouncement]) -> dict:
        """공고 목록에서 입찰 특성을 분석합니다."""
        bid_methods: Counter = Counter()
        contract_methods: Counter = Counter()
        regions: Counter = Counter()
        budgets = []

        for bid in bids:
            if bid.bid_method:
                bid_methods[bid.bid_method] += 1
            if bid.contract_method:
                contract_methods[bid.contract_method] += 1
            if bid.region:
                regions[bid.region] += 1
            if bid.budget and bid.budget > 0:
                budgets.append(bid.budget)

        return {
            "common_bid_methods": [
                {"method": m, "count": c}
                for m, c in bid_methods.most_common(5)
            ],
            "common_contract_methods": [
                {"method": m, "count": c}
                for m, c in contract_methods.most_common(5)
            ],
            "avg_budget": int(sum(budgets) / len(budgets)) if budgets else 0,
            "region_distribution": [
                {"region": r, "count": c}
                for r, c in regions.most_common(5)
            ],
        }

    @staticmethod
    def _analyze_award_stats(awards: list[AwardInfo]) -> dict:
        """낙찰 이력에서 통계를 산출합니다."""
        bid_rates = [a.bid_rate for a in awards if a.bid_rate and a.bid_rate > 0]
        amounts = [a.award_amount for a in awards if a.award_amount and a.award_amount > 0]

        return {
            "avg_bid_rate": round(
                sum(bid_rates) / len(bid_rates), 2
            ) if bid_rates else 0,
            "avg_award_amount": int(
                sum(amounts) / len(amounts)
            ) if amounts else 0,
        }

    @staticmethod
    def _filter_relevant_bids(
        title: str,
        similar_bids: list[BidAnnouncement],
        org_name: str = "",
    ) -> list[BidAnnouncement]:
        """
        유사 공고 중 실제 관련성 높은 공고만 필터링합니다.

        제목의 핵심 키워드가 2개 이상 일치하는 공고만 선택합니다.
        """
        # 핵심 키워드 추출 (불용어 제외)
        stopwords = {"입찰", "공고", "용역", "사업", "구매", "조달", "계약", "시행", "관련", "기타", "위한", "년도"}
        words = re.findall(r'[가-힣]{2,}|[A-Za-z]{3,}', title)
        keywords = {w for w in words if w not in stopwords}

        if not keywords:
            return []

        relevant = []
        for bid in similar_bids:
            if not bid.title:
                continue

            bid_words = set(re.findall(r'[가-힣]{2,}|[A-Za-z]{3,}', bid.title))
            # 키워드 일치 수 계산
            match_count = len(keywords & bid_words)

            # 2개 이상 키워드 일치 시 관련 공고로 판단
            if match_count >= 2:
                relevant.append(bid)
            # 동일 기관이면 1개 키워드만 일치해도 포함
            elif match_count >= 1 and org_name and bid.org_name and org_name in bid.org_name:
                relevant.append(bid)

        return relevant

    @staticmethod
    def _generate_recurring_summary(
        relevant_bids: list[BidAnnouncement],
        budget_history: list[dict],
        org_name: str,
    ) -> str:
        """반복사업 패턴 요약 문자열을 생성합니다."""
        parts = []

        # 발주 횟수
        parts.append(f"과거 {len(relevant_bids)}건의 유사 공고가 발견되었습니다.")

        # 기관 정보
        org_names = {b.org_name for b in relevant_bids if b.org_name}
        if org_names:
            if len(org_names) == 1:
                parts.append(f"발주기관: {list(org_names)[0]}")
            else:
                parts.append(f"관련 기관: {', '.join(list(org_names)[:3])}")

        # 예산 변화
        if len(budget_history) >= 2:
            first_budget = budget_history[0]["budget"]
            last_budget = budget_history[-1]["budget"]
            if first_budget and last_budget and first_budget > 0:
                change_rate = (last_budget - first_budget) / first_budget * 100
                if change_rate > 0:
                    parts.append(f"예산이 {change_rate:.1f}% 증가하는 추세입니다.")
                elif change_rate < 0:
                    parts.append(f"예산이 {abs(change_rate):.1f}% 감소하는 추세입니다.")
                else:
                    parts.append("예산이 유지되고 있습니다.")

        return " ".join(parts)

    @staticmethod
    def _empty_org_result(org_name: str) -> dict:
        """데이터가 없을 때 반환하는 빈 결과 구조."""
        return {
            "org_name": org_name,
            "total_bids": 0,
            "total_awards": 0,
            "top_categories": [],
            "budget_trends": {},
            "preferred_vendors": [],
            "bid_characteristics": {
                "common_bid_methods": [],
                "common_contract_methods": [],
                "avg_budget": 0,
                "region_distribution": [],
            },
            "award_stats": {
                "avg_bid_rate": 0,
                "avg_award_amount": 0,
            },
        }
