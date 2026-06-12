"""
적격심사 및 정량평가 시뮬레이터 모듈 (Bid Simulator)

사업자의 경영상태(신용평가등급), 수행실적, 신인도 가점 등을 활용하여
특정 용역 공고 입찰 참여 시의 정량 평가 점수를 가상으로 시뮬레이션하고,
부족한 점수를 보완하기 위한 공동수급(컨소시엄) 및 신인도 가점 확보 전략을 도출합니다.
"""

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


class BidSimulator:
    """
    용역 입찰 정량평가 및 적격심사 시뮬레이터
    """

    def __init__(self):
        # 신용평가등급별 표준 경영상태 배점표 (30점 만점 기준)
        self.credit_score_table = {
            "AAA": 30.0, "AA+": 30.0, "AA": 30.0, "AA-": 30.0,
            "A+": 30.0, "A": 30.0, "A-": 30.0,
            "BBB+": 28.5, "BBB": 28.0, "BBB-": 27.0,
            "BB+": 25.5, "BB": 25.0, "BB-": 24.0,
            "B+": 22.0, "B": 21.0, "B-": 20.0,
            "CCC+": 15.0,
        }

    def simulate(self, business_profile: dict, bid: dict) -> dict:
        """
        정량평가 시뮬레이션을 수행하고 스코어카드와 보완 전략을 반환합니다.
        
        Args:
            business_profile: 사업자 프로필 dict
            bid: 공고 정보 dict
            
        Returns:
            시뮬레이션 결과 dict
        """
        logger.info("정량평가 시뮬레이션 시작: %s ↔ %s", 
                    business_profile.get("company_name", ""), bid.get("title", ""))
        
        budget = bid.get("budget", bid.get("presmptPrce", 0))
        if budget is None:
            budget = 0
            
        # 1. 경영상태 평가 (30점 만점)
        credit_rating = business_profile.get("credit_rating", "BBB")  # 디폴트 BBB
        credit_score = self.credit_score_table.get(credit_rating.upper(), 25.0)
        
        # 2. 수행실적 평가 (30점 만점)
        # 사업자의 최근 3년 유사 실적 합계 계산
        past_projects = business_profile.get("past_projects", [])
        similar_experience_total = 0
        
        # 간단한 키워드 매칭을 통해 유사 실적만 선별하여 합산
        bid_title = bid.get("title", "")
        keywords = [k for k in ["AI", "데이터", "클라우드", "SW", "개발", "시스템", "컨설팅", "보안"] if k in bid_title]
        
        for proj in past_projects:
            proj_name = proj.get("name", "")
            amount = proj.get("amount", 0)  # 만 원 단위
            
            # 키워드가 겹치거나 전체 실적의 일부를 유사 실적으로 인정
            is_similar = False
            if not keywords:
                is_similar = True
            else:
                for kw in keywords:
                    if kw in proj_name:
                        is_similar = True
                        break
            
            if is_similar:
                similar_experience_total += amount

        # 예산 대비 유사실적 비율 계산
        experience_score = 15.0  # 기본 점수
        ratio = 0.0
        if budget > 0:
            # budget(만원 단위로 통일 필요, schemas에서 이미 budget은 int로 저장)
            # 만약 budget이 원 단위라면 만원 단위로 환산해서 비교
            budget_val = budget
            if budget_val > 1000000:  # 100만 이상이면 원 단위로 추정하여 만원 단위로 변환
                budget_val = budget_val // 10000
            
            ratio = similar_experience_total / budget_val
            
            if ratio >= 1.0:
                experience_score = 30.0
            elif ratio >= 0.7:
                experience_score = 27.0
            elif ratio >= 0.5:
                experience_score = 24.0
            elif ratio >= 0.3:
                experience_score = 21.0
            else:
                experience_score = 18.0
        else:
            # 예산 정보 없으면 24점 중립 처리
            experience_score = 24.0

        # 3. 신인도 가점 평가 (최대 5점)
        val_added_score = 0.0
        company_type = business_profile.get("company_type", "")
        # 여성기업, 장애인기업, 사회적기업 등 우대
        reasons = []
        if "여성" in company_type:
            val_added_score += 1.0
            reasons.append("여성기업 (+1.0)")
        if "사회적" in company_type or "협동조합" in company_type:
            val_added_score += 1.5
            reasons.append("사회적기업/협동조합 (+1.5)")
        
        # 특허나 이노비즈 등 기술인증 보유 시 가점
        licenses = business_profile.get("licenses", [])
        licenses_str = " ".join(licenses)
        if "특허" in licenses_str or "기술인증" in licenses_str or "이노비즈" in licenses_str:
            val_added_score += 1.5
            reasons.append("기술 우수 인증/특허 보유 (+1.5)")
            
        val_added_score = min(val_added_score, 5.0)  # 가점 한도 5점

        # 4. 감점 요인 (최대 -5점)
        deduction_score = 0.0
        # 프로필 상 제재 이력이 있으면 감점
        if business_profile.get("has_sanctions", False):
            deduction_score = -2.0
            reasons.append("부정당업자 처분 이력 (-2.0)")

        # 5. 정량 평가 합산 점수 (경영상태 30 + 실적 30 + 가점 - 감점)
        total_quantitative_score = credit_score + experience_score + val_added_score + deduction_score
        total_quantitative_score = min(total_quantitative_score, 65.0)  # 정량 한계점 조율

        # 6. 부족점수 보완 및 낙찰 선정 전략 수립
        pass_threshold = 57.0  # 통상적인 적격심사 통과를 위한 정량 안정권 점수 (협상에 의한 계약의 경우 정량 20%~30%)
        # 30점 만점 기준 환산 등으로 점수 대역이 달라질 수 있으므로, 협상에 의한 계약 기준(정량 20점 만점 환산 등)을 표기
        
        # 보완 전략 추천 엔진
        recommendations = []
        status = "안정"
        
        if total_quantitative_score < pass_threshold:
            status = "위험 (정량 점수 부족)"
            # 실적 보완 전략
            if experience_score < 24.0:
                recommendations.append(
                    "💡 [공동수급(컨소시엄) 구성 전략]: 본사 실적(약 {:.1f}%)이 부족하므로, "
                    "동일 분야 실적을 다수 보유한 파트너사와 6:4 혹은 5:5 비율의 공동수급체 구성을 권장합니다."
                    .format(ratio * 100)
                )
            # 신인도 가점 보완 전략
            if val_added_score < 3.0:
                recommendations.append(
                    "💡 [신인도 가점 보완]: 신인도 가점이 부족합니다. 입찰 공동도급 시 여성기업/장애인기업/사회적기업을 "
                    "공동수급체 구성원으로 포함하여 지분율을 배정하면 신인도 가점(최대 1.5점)을 획득할 수 있습니다."
                )
            # 경영상태 보완 전략
            if credit_score < 27.0:
                recommendations.append(
                    "💡 [경영상태 보완]: 신용평가등급이 {}등급으로 경영상태 배점에서 감점이 예상됩니다. "
                    "차기 입찰을 위해 신용등급 개선 컨설팅을 받거나, 경영상태 평가 비율이 낮거나 적격심사가 면제되는 "
                    "소액 수의계약/지원사업 공고를 집중 탐색하시기 바랍니다.".format(credit_rating)
                )
        else:
            recommendations.append(
                "🟢 [정량 평가 안정권]: 현재 경영상태 및 수행 실적 점수가 안정권입니다. "
                "제안서(정성평가)의 핵심 가치 제안(Win Theme) 수립 및 고도화에 자원을 집중하십시오."
            )

        scorecard = {
            "credit_evaluation": {
                "rating": credit_rating,
                "score": credit_score,
                "max_score": 30.0,
                "detail": "신용평가등급 기반 배점"
            },
            "experience_evaluation": {
                "similar_experience_total_krw": similar_experience_total * 10000,  # 원 단위
                "ratio_to_budget": round(ratio, 3),
                "score": experience_score,
                "max_score": 30.0,
                "detail": "최근 3년 유사 용역 실적 대비 배점"
            },
            "value_added": {
                "score": val_added_score,
                "reasons": reasons
            },
            "total_score": round(total_quantitative_score, 2),
            "pass_threshold": pass_threshold,
            "status": status
        }

        return {
            "scorecard": scorecard,
            "strategies": recommendations
        }
