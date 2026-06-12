"""
적격심사 및 정량평가 시뮬레이터 단위 테스트 모듈
"""

import pytest
from src.analyzers.bid_simulator import BidSimulator


def test_bid_simulator_perfect_score():
    """만점 조건에서의 시뮬레이션 검증"""
    simulator = BidSimulator()
    
    # 30점짜리 신용도(AAA) 및 예산 1억 대비 3억 실적을 지닌 만점 가깝거나 넘는 조건
    business_profile = {
        "company_name": "테스트만점기업",
        "credit_rating": "AAA",
        "past_projects": [
            {"name": "AI 기반 시뮬레이터 개발 사업", "amount": 30000}  # 3억 원
        ],
        "company_type": "여성기업, 사회적협동조합",
        "licenses": ["소프트웨어사업자", "정보통신공공특허"]
    }
    
    # 예산 1억 원 (만원 단위: 10000)
    bid = {
        "title": "AI 시스템 개발 입찰 공고",
        "budget": 10000,
        "required_licenses": ["소프트웨어사업자"]
    }
    
    result = simulator.simulate(business_profile, bid)
    
    assert "scorecard" in result
    assert "strategies" in result
    
    scorecard = result["scorecard"]
    assert scorecard["credit_evaluation"]["score"] == 30.0
    assert scorecard["experience_evaluation"]["score"] == 30.0
    assert scorecard["value_added"]["score"] >= 4.0
    assert scorecard["total_score"] >= 57.0
    assert scorecard["status"] == "안정"
    assert "정량 평가 안정권" in result["strategies"][0]


def test_bid_simulator_low_score():
    """점수가 낮아 보완 전략이 도출되는 위험 상태 검증"""
    simulator = BidSimulator()
    
    # 신용도 B등급 및 실적이 전혀 없는 위험 조건
    business_profile = {
        "company_name": "테스트스타트업",
        "credit_rating": "B",
        "past_projects": [],
        "company_type": "일반기업",
        "licenses": []
    }
    
    # 예산 5억 원 (만원 단위: 50000)
    bid = {
        "title": "AI 기반 빅데이터 플랫폼 구축 용역",
        "budget": 50000
    }
    
    result = simulator.simulate(business_profile, bid)
    
    scorecard = result["scorecard"]
    assert scorecard["credit_evaluation"]["score"] == 21.0
    assert scorecard["experience_evaluation"]["score"] == 18.0
    assert scorecard["value_added"]["score"] == 0.0
    assert scorecard["status"] == "위험 (정량 점수 부족)"
    
    # 보완 전략 검증
    strategies = result["strategies"]
    assert len(strategies) > 0
    assert any("공동수급(컨소시엄)" in s for s in strategies)
    assert any("신인도 가점" in s for s in strategies)
    assert any("경영상태 보완" in s for s in strategies)
