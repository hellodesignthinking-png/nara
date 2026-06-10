"""
NARA Analyzer 테스트 공통 fixture

pytest conftest.py — 임시 DB, mock config 등 공통 테스트 인프라를 정의합니다.
"""

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# 프로젝트 루트를 sys.path에 추가
PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture
def tmp_db_path(tmp_path):
    """임시 SQLite DB 파일 경로를 제공합니다."""
    return tmp_path / "test_nara.db"


@pytest.fixture
def db_manager(tmp_db_path):
    """초기화된 DatabaseManager 인스턴스를 제공합니다."""
    from src.models.database import DatabaseManager

    db = DatabaseManager(tmp_db_path)
    db.connect()
    db.init_db()
    yield db
    db.close()


@pytest.fixture
def mock_config(tmp_path):
    """테스트용 Config 객체를 제공합니다 (모든 API 키 비활성화)."""
    from src.config import Config

    return Config(
        data_go_kr_api_key="test_api_key_12345",
        naver_client_id="test_naver_id",
        naver_client_secret="test_naver_secret",
        openai_api_key="",
        gemini_api_key="",
        llm_engine="gemini",
        keywords=["AI", "빅데이터", "클라우드", "SW개발"],
        min_relevance_score=40,
        past_years=2,
        db_path=tmp_path / "test_nara.db",
    )


@pytest.fixture
def sample_bid_dict():
    """테스트용 입찰공고 딕셔너리를 반환합니다."""
    return {
        "bid_ntce_no": "20240101001",
        "bid_ntce_ord": "00",
        "title": "2024년 AI 기반 데이터 분석 시스템 구축",
        "org_name": "서울특별시",
        "demand_org_name": "서울특별시 디지털정책관",
        "budget": 500000000,
        "bid_begin_dt": "2024-01-15 09:00:00",
        "bid_close_dt": "2024-02-15 18:00:00",
        "category": "소프트웨어개발",
        "bid_method": "일반경쟁",
        "contract_method": "협상에 의한 계약",
        "region": "서울",
        "license_limit": "소프트웨어사업자",
        "rfp_url": None,
        "rfp_text": None,
    }


@pytest.fixture
def sample_bid_api_response():
    """공공데이터포털 API 응답 형식의 테스트 데이터를 반환합니다."""
    return {
        "response": {
            "header": {
                "resultCode": "00",
                "resultMsg": "NORMAL SERVICE",
            },
            "body": {
                "items": [
                    {
                        "bidNtceNo": "20240101001",
                        "bidNtceOrd": "00",
                        "bidNtceNm": "2024년 AI 기반 데이터 분석 시스템 구축",
                        "ntceInsttNm": "서울특별시",
                        "dminsttNm": "서울특별시 디지털정책관",
                        "presmptPrce": "500000000",
                        "bidBeginDt": "2024-01-15 09:00:00",
                        "bidClseDt": "2024-02-15 18:00:00",
                        "industryCdNm": "소프트웨어개발",
                        "bidMethdNm": "일반경쟁",
                        "cntrctMthdNm": "협상에 의한 계약",
                    },
                    {
                        "bidNtceNo": "20240101002",
                        "bidNtceOrd": "00",
                        "bidNtceNm": "빅데이터 플랫폼 운영 용역",
                        "ntceInsttNm": "한국데이터산업진흥원",
                        "presmptPrce": "300000000",
                        "bidBeginDt": "2024-01-16 09:00:00",
                        "bidClseDt": "2024-02-16 18:00:00",
                    },
                ],
                "totalCount": 2,
                "numOfRows": 100,
                "pageNo": 1,
            },
        }
    }


@pytest.fixture
def sample_business_profile_dict():
    """테스트용 사업자 프로필 딕셔너리를 반환합니다."""
    return {
        "biz_id": "1234567890",
        "company_name": "테스트 IT솔루션",
        "ceo_name": "홍길동",
        "business_types": ["SW개발", "AI", "데이터분석"],
        "licenses": ["소프트웨어사업자", "정보통신공사업"],
        "regions": ["서울", "경기"],
        "past_projects": [
            {"name": "공공 AI 플랫폼 구축", "year": "2023", "amount": 40000},
            {"name": "빅데이터 분석 시스템", "year": "2022", "amount": 25000},
        ],
        "annual_revenue": 5000000000,
        "employee_count": 50,
        "keywords": ["AI", "빅데이터", "클라우드"],
        "min_budget": 100000000,
        "max_budget": 1000000000,
    }


@pytest.fixture
def sample_award_dict():
    """테스트용 낙찰정보 딕셔너리를 반환합니다."""
    return {
        "bid_ntce_no": "20230501001",
        "bid_title": "2023년 AI 시스템 구축",
        "winner_name": "에이아이테크",
        "award_amount": 450000000,
        "bid_rate": 89.5,
        "award_date": "2023-06-01",
        "budget": 500000000,
    }


@pytest.fixture
def sample_news_dict():
    """테스트용 뉴스기사 딕셔너리를 반환합니다."""
    return {
        "title": "서울시, AI 기반 행정 서비스 확대 추진",
        "description": "서울특별시는 2024년부터 AI 기반 행정 서비스를 확대하겠다고 발표했다.",
        "link": "https://example.com/news/12345",
        "pub_date": "2024-01-10",
        "search_query": "서울특별시 AI",
    }
