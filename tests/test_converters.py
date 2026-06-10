"""converters 모듈 테스트"""
import pytest
from unittest.mock import MagicMock
from src.utils.converters import biz_profile_to_matcher_dict, bid_to_matcher_dict


class TestBizProfileToMatcherDict:
    """biz_profile_to_matcher_dict 함수 테스트"""

    def test_basic_conversion(self):
        """기본 변환 테스트"""
        profile = MagicMock()
        profile.biz_id = "1234567890"
        profile.company_name = "테스트 회사"
        profile.business_types = ["SI", "컨설팅"]
        profile.regions = ["서울"]
        profile.employee_count = 50
        profile.annual_revenue = 1000000000
        profile.min_budget = 100000000
        profile.max_budget = 500000000
        profile.keywords = ["AI", "빅데이터"]
        profile.licenses = ["정보통신공사업"]
        profile.past_projects = ["프로젝트1"]

        result = biz_profile_to_matcher_dict(profile)

        assert result["company_name"] == "테스트 회사"
        assert result["region"] == "서울"
        assert result["employee_count"] == 50

    def test_empty_regions(self):
        """지역 정보 없는 경우"""
        profile = MagicMock()
        profile.biz_id = "1234567890"
        profile.company_name = "테스트"
        profile.business_types = []
        profile.regions = []
        profile.employee_count = 0
        profile.annual_revenue = 0
        profile.min_budget = None
        profile.max_budget = None
        profile.keywords = []
        profile.licenses = []
        profile.past_projects = []

        result = biz_profile_to_matcher_dict(profile)
        assert result["region"] == ""

    def test_max_budget_none(self):
        """max_budget이 None인 경우"""
        profile = MagicMock()
        profile.biz_id = "1234567890"
        profile.company_name = "테스트"
        profile.business_types = []
        profile.regions = []
        profile.employee_count = 0
        profile.annual_revenue = 0
        profile.min_budget = None
        profile.max_budget = None
        profile.keywords = []
        profile.licenses = []
        profile.past_projects = []

        result = biz_profile_to_matcher_dict(profile)
        assert result["budget_range"]["max"] == 999999999999

    def test_max_budget_zero(self):
        """max_budget이 0인 경우 (수정 후 0이 유지되어야 함)"""
        profile = MagicMock()
        profile.biz_id = "1234567890"
        profile.company_name = "테스트"
        profile.business_types = []
        profile.regions = []
        profile.employee_count = 0
        profile.annual_revenue = 0
        profile.min_budget = 0
        profile.max_budget = 0
        profile.keywords = []
        profile.licenses = []
        profile.past_projects = []

        result = biz_profile_to_matcher_dict(profile)
        # max_budget=0 은 명시적 값이므로 0이 유지되어야 함
        assert result["budget_range"]["max"] == 0


class TestBidToMatcherDict:
    """bid_to_matcher_dict 함수 테스트"""

    def test_dict_input(self):
        """dict 입력 테스트"""
        bid = {"title": "테스트 공고", "budget": 1000000}
        result = bid_to_matcher_dict(bid)
        assert result == bid

    def test_object_input(self):
        """BidAnnouncement 객체 입력 테스트"""
        bid = MagicMock()
        bid.bid_ntce_no = "20250001"
        bid.title = "AI 시스템 구축"
        bid.budget = 500000000
        bid.org_name = "테스트 기관"
        bid.demand_org_name = "수요 기관"
        bid.bid_method = "일반경쟁"
        bid.contract_type = "용역"
        bid.region = "서울"
        bid.category = "소프트웨어"
        bid.license_limit = "소프트웨어사업자"
        bid.bid_close_dt = "2025-12-31"
        bid.rfp_url = "https://example.com"
        bid.rfp_text = "RFP 내용"

        result = bid_to_matcher_dict(bid)
        assert result["title"] == "AI 시스템 구축"
        assert result["budget"] == 500000000
        assert result["bid_ntce_no"] == "20250001"
