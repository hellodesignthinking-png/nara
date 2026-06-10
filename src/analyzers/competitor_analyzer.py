"""
경쟁사 분석 모듈

입찰 공고에 대한 경쟁사 현황을 분석합니다.
과거 낙찰 데이터를 기반으로 경쟁사 목록, 시장 집중도,
개별 업체의 수주 패턴을 파악하여 입찰 전략 수립에 활용합니다.
"""

import logging
from collections import Counter, defaultdict
from typing import Optional

from src.models.database import DatabaseManager
from src.models.schemas import AwardInfo

logger = logging.getLogger(__name__)


class CompetitorAnalyzer:
    """
    경쟁사 분석 클래스

    과거 낙찰 데이터를 활용하여 경쟁사 현황을 분석합니다.
    유사 공고의 낙찰 이력에서 경쟁사를 식별하고,
    시장 집중도 및 개별 업체의 수주 패턴을 분석합니다.
    """

    def find_competitors_for_bid(
        self,
        db: DatabaseManager,
        bid_dict: dict,
    ) -> dict:
        """
        특정 공고에 대한 잠재적 경쟁사를 식별합니다.

        공고 제목의 키워드로 유사한 과거 낙찰 건을 검색하고,
        해당 건의 낙찰 업체들을 경쟁사 후보로 추출합니다.

        Args:
            db: DatabaseManager 인스턴스
            bid_dict: 입찰공고 정보 딕셔너리
                - title (str): 공고명
                - org_name (str, optional): 발주기관명
                - budget (int, optional): 추정가격

        Returns:
            {
                "bid_title": 공고명,
                "competitors": 경쟁사 분석 결과 (analyze_competitors의 반환값),
                "data_count": 분석에 사용된 낙찰 데이터 건수,
            }
        """
        title = bid_dict.get("title", "")
        if not title:
            logger.warning("공고 제목이 비어있어 경쟁사 분석을 건너뜁니다.")
            return {"bid_title": "", "competitors": {}, "data_count": 0}

        logger.info("경쟁사 분석 시작: %s", title)

        # 제목 키워드로 과거 낙찰 이력 검색
        past_awards = db.get_awards_by_title(title, limit=200)

        # 발주기관 데이터도 추가로 수집
        org_name = bid_dict.get("org_name", "")
        if org_name:
            org_awards = db.get_awards_by_org(org_name, limit=100)
            # 중복 제거 (bid_ntce_no + winner_name 기준)
            existing_keys = {
                (a.bid_ntce_no, a.winner_name) for a in past_awards
            }
            for award in org_awards:
                key = (award.bid_ntce_no, award.winner_name)
                if key not in existing_keys:
                    past_awards.append(award)
                    existing_keys.add(key)

        if not past_awards:
            logger.info("유사 낙찰 이력이 없어 경쟁사 분석 결과가 없습니다.")
            return {
                "bid_title": title,
                "competitors": self._empty_competitor_result(),
                "data_count": 0,
            }

        # 낙찰 데이터를 딕셔너리 리스트로 변환하여 분석
        award_dicts = [a.to_dict() for a in past_awards]
        competitors = self.analyze_competitors(bid_dict, award_dicts)

        logger.info(
            "경쟁사 분석 완료: %d건 데이터, %d개 업체 식별",
            len(past_awards),
            len(competitors.get("top_competitors", [])),
        )

        return {
            "bid_title": title,
            "competitors": competitors,
            "data_count": len(past_awards),
        }

    def analyze_competitors(
        self,
        bid_dict: dict,
        past_awards: list[dict],
    ) -> dict:
        """
        과거 낙찰 데이터에서 경쟁사 패턴을 분석합니다.

        Args:
            bid_dict: 현재 입찰공고 정보 딕셔너리
            past_awards: 과거 낙찰 이력 딕셔너리 리스트
                각 항목은 AwardInfo.to_dict() 형식

        Returns:
            {
                "top_competitors": [  # 상위 경쟁사 목록 (낙찰 횟수 기준)
                    {
                        "name": 업체명,
                        "win_count": 낙찰 횟수,
                        "win_rate": 전체 대비 낙찰 비율 (%),
                        "avg_bid_rate": 평균 투찰률,
                        "avg_award_amount": 평균 낙찰금액,
                        "recent_win_date": 최근 낙찰일,
                    }, ...
                ],
                "market_concentration": {  # 시장 집중도
                    "hhi": HHI 지수 (0~10000),
                    "level": "높음" | "보통" | "낮음",
                    "top3_share": 상위 3개 업체 점유율 (%),
                },
                "competitive_position": {  # 경쟁 환경 요약
                    "total_competitors": 전체 경쟁사 수,
                    "total_awards": 전체 낙찰 건수,
                    "avg_bid_rate": 전체 평균 투찰률,
                    "budget_range": {"min": 최소, "max": 최대, "avg": 평균},
                },
            }
        """
        if not past_awards:
            return self._empty_competitor_result()

        # 업체별 낙찰 데이터 집계
        competitor_data: dict[str, list[dict]] = defaultdict(list)
        for award in past_awards:
            winner = award.get("winner_name")
            if winner:
                competitor_data[winner].append(award)

        total_awards = len(past_awards)

        # 상위 경쟁사 분석 (낙찰 횟수 기준 상위 10개)
        top_competitors = []
        for name, awards in sorted(
            competitor_data.items(),
            key=lambda x: len(x[1]),
            reverse=True,
        )[:10]:
            bid_rates = [
                a["bid_rate"] for a in awards
                if a.get("bid_rate") and a["bid_rate"] > 0
            ]
            amounts = [
                a["award_amount"] for a in awards
                if a.get("award_amount") and a["award_amount"] > 0
            ]
            dates = [
                a["award_date"] for a in awards
                if a.get("award_date")
            ]

            top_competitors.append({
                "name": name,
                "win_count": len(awards),
                "win_rate": round(len(awards) / total_awards * 100, 1),
                "avg_bid_rate": round(sum(bid_rates) / len(bid_rates), 2) if bid_rates else 0,
                "avg_award_amount": int(sum(amounts) / len(amounts)) if amounts else 0,
                "recent_win_date": max(dates) if dates else None,
            })

        # 시장 집중도 분석 (HHI: Herfindahl-Hirschman Index)
        market_shares = [
            len(awards) / total_awards * 100
            for awards in competitor_data.values()
        ]
        hhi = sum(s ** 2 for s in market_shares)
        top3_share = sum(
            sorted(market_shares, reverse=True)[:3]
        ) if market_shares else 0

        if hhi >= 2500:
            concentration_level = "높음"
        elif hhi >= 1500:
            concentration_level = "보통"
        else:
            concentration_level = "낮음"

        # 경쟁 환경 요약
        all_bid_rates = [
            a.get("bid_rate", 0) for a in past_awards
            if a.get("bid_rate") and a["bid_rate"] > 0
        ]
        all_budgets = [
            a.get("budget", 0) for a in past_awards
            if a.get("budget") and a["budget"] > 0
        ]

        competitive_position = {
            "total_competitors": len(competitor_data),
            "total_awards": total_awards,
            "avg_bid_rate": round(
                sum(all_bid_rates) / len(all_bid_rates), 2
            ) if all_bid_rates else 0,
            "budget_range": {
                "min": min(all_budgets) if all_budgets else 0,
                "max": max(all_budgets) if all_budgets else 0,
                "avg": int(sum(all_budgets) / len(all_budgets)) if all_budgets else 0,
            },
        }

        return {
            "top_competitors": top_competitors,
            "market_concentration": {
                "hhi": round(hhi, 1),
                "level": concentration_level,
                "top3_share": round(top3_share, 1),
            },
            "competitive_position": competitive_position,
        }

    def analyze_winner_pattern(
        self,
        db: DatabaseManager,
        winner_name: str,
    ) -> dict:
        """
        특정 업체의 수주 패턴을 심층 분석합니다.

        업체의 과거 낙찰 이력에서 선호 분야, 투찰률 패턴,
        예산 규모별 분포, 시간대별 추이를 분석합니다.

        Args:
            db: DatabaseManager 인스턴스
            winner_name: 분석 대상 업체명

        Returns:
            {
                "winner_name": 업체명,
                "total_wins": 총 낙찰 건수,
                "bid_rate_stats": {  # 투찰률 통계
                    "avg": 평균, "min": 최소, "max": 최대, "std": 표준편차,
                },
                "amount_stats": {  # 낙찰금액 통계
                    "avg": 평균, "min": 최소, "max": 최대, "total": 합계,
                },
                "preferred_categories": [  # 선호 분야 (공고명 키워드 기반)
                    {"keyword": 키워드, "count": 빈도}, ...
                ],
                "yearly_trend": {  # 연도별 추이
                    "2024": {"count": 건수, "total_amount": 합계}, ...
                },
                "recent_awards": [  # 최근 5건 낙찰 이력
                    {"title": 공고명, "amount": 금액, "date": 날짜}, ...
                ],
            }
        """
        logger.info("업체 패턴 분석 시작: %s", winner_name)

        awards = db.get_awards_by_winner(winner_name, limit=200)
        if not awards:
            logger.info("낙찰 이력 없음: %s", winner_name)
            return {
                "winner_name": winner_name,
                "total_wins": 0,
                "bid_rate_stats": {},
                "amount_stats": {},
                "preferred_categories": [],
                "yearly_trend": {},
                "recent_awards": [],
            }

        # 투찰률 통계
        bid_rates = [a.bid_rate for a in awards if a.bid_rate and a.bid_rate > 0]
        bid_rate_stats = {}
        if bid_rates:
            import statistics
            bid_rate_stats = {
                "avg": round(statistics.mean(bid_rates), 2),
                "min": round(min(bid_rates), 2),
                "max": round(max(bid_rates), 2),
                "std": round(statistics.stdev(bid_rates), 2) if len(bid_rates) > 1 else 0,
            }

        # 낙찰금액 통계
        amounts = [a.award_amount for a in awards if a.award_amount and a.award_amount > 0]
        amount_stats = {}
        if amounts:
            amount_stats = {
                "avg": int(sum(amounts) / len(amounts)),
                "min": min(amounts),
                "max": max(amounts),
                "total": sum(amounts),
            }

        # 선호 분야 분석 (공고명에서 키워드 추출)
        import re
        keyword_counter: Counter = Counter()
        for a in awards:
            if a.bid_title:
                # 2글자 이상의 한글/영문 단어 추출
                words = re.findall(r'[가-힣]{2,}|[A-Za-z]{3,}', a.bid_title)
                # 일반적인 불용어 제외
                stopwords = {"입찰", "공고", "용역", "사업", "구매", "조달", "계약", "시행", "관련", "기타", "위한"}
                keywords = [w for w in words if w not in stopwords]
                keyword_counter.update(keywords)

        preferred_categories = [
            {"keyword": kw, "count": cnt}
            for kw, cnt in keyword_counter.most_common(10)
        ]

        # 연도별 추이
        yearly_trend: dict[str, dict] = defaultdict(lambda: {"count": 0, "total_amount": 0})
        for a in awards:
            if a.award_date:
                year = a.award_date[:4]  # "YYYY-MM-DD" → "YYYY"
                yearly_trend[year]["count"] += 1
                if a.award_amount:
                    yearly_trend[year]["total_amount"] += a.award_amount

        # 최근 5건 낙찰 이력
        sorted_awards = sorted(
            awards,
            key=lambda a: a.award_date or "",
            reverse=True,
        )
        recent_awards = [
            {
                "title": a.bid_title,
                "amount": a.award_amount,
                "bid_rate": a.bid_rate,
                "date": a.award_date,
            }
            for a in sorted_awards[:5]
        ]

        result = {
            "winner_name": winner_name,
            "total_wins": len(awards),
            "bid_rate_stats": bid_rate_stats,
            "amount_stats": amount_stats,
            "preferred_categories": preferred_categories,
            "yearly_trend": dict(yearly_trend),
            "recent_awards": recent_awards,
        }

        logger.info(
            "업체 패턴 분석 완료: %s (총 %d건, 선호분야 %d개)",
            winner_name, len(awards), len(preferred_categories),
        )
        return result

    @staticmethod
    def _empty_competitor_result() -> dict:
        """분석 데이터가 없을 때 반환하는 빈 결과 구조."""
        return {
            "top_competitors": [],
            "market_concentration": {
                "hhi": 0,
                "level": "데이터 없음",
                "top3_share": 0,
            },
            "competitive_position": {
                "total_competitors": 0,
                "total_awards": 0,
                "avg_bid_rate": 0,
                "budget_range": {"min": 0, "max": 0, "avg": 0},
            },
        }
