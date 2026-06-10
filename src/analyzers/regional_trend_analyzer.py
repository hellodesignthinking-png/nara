"""
지역/도시 트렌드 분석 모듈

지역별 공공조달 시장 트렌드, 정책 방향, 지역 업체 우대 패턴을 분석합니다.
"""

import logging
import re
from collections import Counter, defaultdict
from typing import Optional

logger = logging.getLogger(__name__)


class RegionalTrendAnalyzer:
    """
    지역/도시별 공공조달 트렌드를 분석합니다.
    지자체의 예산 방향, 중점 사업, 지역 업체 우대 패턴 등을 파악합니다.
    """

    # 17개 시·도 정책 키워드 매핑
    REGIONAL_POLICY_KEYWORDS = {
        "서울": ["스마트도시", "디지털전환", "AI행정", "탄소중립", "자치분권", "도시재생"],
        "부산": ["해양", "물류", "블록체인", "글로벌허브", "북항재개발", "영화산업"],
        "대구": ["의료", "로봇", "섬유", "자동차부품", "스마트시티"],
        "인천": ["바이오", "항공", "물류", "경제자유구역", "메타버스"],
        "광주": ["AI", "자동차", "에너지", "문화예술", "광산업"],
        "대전": ["과학기술", "연구개발", "바이오", "ICT", "우주항공"],
        "울산": ["수소경제", "조선해양", "석유화학", "자동차", "에코델타"],
        "세종": ["자율주행", "스마트시티", "데이터센터", "행정중심"],
        "경기": ["반도체", "바이오", "자율주행", "스마트팩토리", "GTX"],
        "강원": ["관광", "바이오", "신재생에너지", "스마트농업", "동계스포츠"],
        "충북": ["바이오", "반도체", "태양광", "오창과학산업단지"],
        "충남": ["내포신도시", "석유화학", "자동차", "농업기술"],
        "전북": ["탄소소재", "농생명", "새만금", "신재생에너지"],
        "전남": ["에너지", "조선", "수산업", "태양광", "여수산단"],
        "경북": ["원자력", "포항제철", "IT융합", "농업혁신"],
        "경남": ["항공우주", "방위산업", "조선", "스마트제조"],
        "제주": ["관광", "전기차", "신재생에너지", "스마트팜", "해양환경"],
    }

    def analyze_regional_trend(self, db, region: str) -> dict:
        """
        지역별 공공조달 시장 트렌드를 분석합니다.

        Args:
            db: DatabaseManager 인스턴스
            region: 지역명 (예: "서울", "경기")

        Returns:
            지역 트렌드 분석 결과 딕셔너리
        """
        logger.info("지역 트렌드 분석 시작: %s", region)

        result = {
            "region": region,
            "market_overview": {},
            "sector_analysis": [],
            "local_preference": {},
            "policy_alignment": {},
        }

        try:
            # 1. 시장 개요: 해당 지역 낙찰 데이터 수집
            awards = db.get_awards_by_region(region, limit=200)

            if not awards:
                result["market_overview"] = {
                    "total_bids": 0,
                    "total_budget": 0,
                    "message": f"{region} 지역의 낙찰 데이터가 없습니다.",
                }
                return result

            total_budget = sum(a.award_amount or 0 for a in awards)
            budgets = [a.award_amount for a in awards if a.award_amount]
            avg_budget = total_budget // len(budgets) if budgets else 0

            result["market_overview"] = {
                "total_awards": len(awards),
                "total_budget": total_budget,
                "avg_award_amount": avg_budget,
            }

            # 2. 분야별 분석: 제목 키워드 기반 카테고리 분류
            sector_counter = Counter()
            sector_budgets = defaultdict(int)
            sector_winners = defaultdict(list)

            for award in awards:
                title = award.bid_title or ""
                sector = self._classify_sector(title)
                sector_counter[sector] += 1
                sector_budgets[sector] += award.award_amount or 0
                if award.winner_name:
                    sector_winners[sector].append(award.winner_name)

            sector_list = []
            for sector, count in sector_counter.most_common(10):
                winners = Counter(sector_winners[sector]).most_common(3)
                bid_rates = [
                    a.bid_rate for a in awards
                    if a.bid_rate and self._classify_sector(a.bid_title or "") == sector
                ]
                sector_list.append({
                    "sector": sector,
                    "bid_count": count,
                    "total_budget": sector_budgets[sector],
                    "top_winners": [w[0] for w in winners],
                    "avg_bid_rate": round(sum(bid_rates) / len(bid_rates), 2) if bid_rates else 0,
                })

            result["sector_analysis"] = sector_list

            # 3. 지역 업체 우대 분석
            result["local_preference"] = self.analyze_local_vendor_preference(db, region)

        except Exception as e:
            logger.warning("지역 트렌드 분석 중 오류: %s", e)

        return result

    def calculate_policy_alignment(self, bid: dict, region: str) -> dict:
        """
        공고와 지역 정책 키워드 부합도를 계산합니다.

        Args:
            bid: 공고 정보 dict (title, category 등)
            region: 지역명

        Returns:
            부합도 분석 결과 (score, matched_keywords, recommendation)
        """
        # 지역 키워드 가져오기 (부분 매칭)
        policy_keywords = []
        for key, keywords in self.REGIONAL_POLICY_KEYWORDS.items():
            if key in region or region in key:
                policy_keywords = keywords
                break

        if not policy_keywords:
            return {
                "score": 0.0,
                "matched_keywords": [],
                "recommendation": f"{region} 지역의 정책 키워드 데이터가 없습니다.",
            }

        # 공고 텍스트 구성
        bid_text = " ".join([
            bid.get("title", ""),
            bid.get("category", ""),
            bid.get("rfp_text", "") or "",
        ]).upper()

        # 매칭 계산
        matched = [kw for kw in policy_keywords if kw.upper() in bid_text]
        score = len(matched) / len(policy_keywords) if policy_keywords else 0.0

        if score >= 0.5:
            recommendation = f"{region} 지역 정책 방향과 높은 부합도 — {', '.join(matched)} 키워드를 제안서에서 강조하세요."
        elif score > 0:
            recommendation = f"{region} 지역 정책 키워드 '{', '.join(matched)}'와 부분적으로 일치합니다. 관련 내용을 보강하세요."
        else:
            recommendation = f"이 공고는 {region} 지역 중점 정책({', '.join(policy_keywords[:3])})과 직접 연관이 적습니다. 간접 연계 포인트를 찾아보세요."

        return {
            "score": round(score, 3),
            "matched_keywords": matched,
            "policy_keywords": policy_keywords,
            "recommendation": recommendation,
        }

    def analyze_local_vendor_preference(self, db, region: str) -> dict:
        """
        지역 업체 우대 패턴을 분석합니다.

        Args:
            db: DatabaseManager 인스턴스
            region: 지역명

        Returns:
            지역 업체 우대 분석 결과
        """
        try:
            awards = db.get_awards_by_region(region, limit=200)
            if not awards:
                return {
                    "local_win_rate": 0,
                    "has_local_preference": False,
                    "recommendation": f"{region} 지역 낙찰 데이터가 부족합니다.",
                }

            # 지역명이 업체명에 포함된 비율 (간접 지표)
            region_short = region.replace("특별시", "").replace("광역시", "").replace("도", "")[:2]
            local_wins = sum(
                1 for a in awards
                if a.winner_name and region_short in a.winner_name
            )
            total = len(awards)
            local_rate = local_wins / total if total > 0 else 0

            has_preference = local_rate > 0.3

            if has_preference:
                rec = f"{region} 지역은 지역 업체 수주 비율이 {local_rate:.0%}로 높습니다. 지역 소재 업체와 컨소시엄을 고려하세요."
            else:
                rec = f"{region} 지역은 지역 제한 없이 전국 업체에 개방적입니다 (지역 업체 비율: {local_rate:.0%})."

            return {
                "local_win_rate": round(local_rate, 3),
                "has_local_preference": has_preference,
                "local_wins": local_wins,
                "total_awards": total,
                "recommendation": rec,
            }
        except Exception as e:
            logger.warning("지역 업체 우대 분석 실패: %s", e)
            return {
                "local_win_rate": 0,
                "has_local_preference": False,
                "recommendation": "분석 데이터가 부족합니다.",
            }

    def _classify_sector(self, title: str) -> str:
        """공고 제목으로 분야를 분류합니다."""
        title_upper = title.upper()

        sector_keywords = {
            "AI/빅데이터": ["AI", "인공지능", "빅데이터", "데이터", "머신러닝", "딥러닝"],
            "SW개발": ["시스템", "소프트웨어", "SW", "플랫폼", "앱", "웹", "포털"],
            "정보보안": ["보안", "정보보호", "사이버", "개인정보"],
            "클라우드/인프라": ["클라우드", "인프라", "서버", "네트워크", "IDC", "데이터센터"],
            "컨설팅": ["컨설팅", "용역", "연구", "조사", "분석", "기획"],
            "유지보수": ["유지보수", "운영", "관리", "위탁"],
            "건설/시설": ["건설", "공사", "시설", "설비", "건축"],
            "교육/훈련": ["교육", "훈련", "연수", "양성"],
        }

        for sector, keywords in sector_keywords.items():
            for kw in keywords:
                if kw in title_upper:
                    return sector
        return "기타"
