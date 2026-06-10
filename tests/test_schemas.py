"""
schemas.py 데이터 모델 테스트

to_dict / from_dict 라운드트립, _parse_json_field 반환 타입 안정화 등을 검증합니다.
"""

import json
import pytest

from src.models.schemas import (
    _parse_json_field,
    _dump_json_field,
    _parse_timestamp,
    _format_timestamp,
    BidAnnouncement,
    AwardInfo,
    NewsArticle,
    AnalysisResult,
    BusinessProfile,
)


class TestParseJsonField:
    """_parse_json_field 반환 타입 테스트 — 항상 list를 반환해야 합니다."""

    def test_none_returns_empty_list(self):
        assert _parse_json_field(None) == []

    def test_empty_string_returns_empty_list(self):
        assert _parse_json_field("") == []
        assert _parse_json_field("   ") == []

    def test_list_returns_same_list(self):
        data = ["a", "b", "c"]
        assert _parse_json_field(data) == data

    def test_dict_returns_list_of_dict(self):
        data = {"key": "value"}
        assert _parse_json_field(data) == [data]

    def test_json_array_string(self):
        result = _parse_json_field('["AI", "빅데이터"]')
        assert result == ["AI", "빅데이터"]

    def test_json_object_string(self):
        result = _parse_json_field('{"name": "test"}')
        assert result == [{"name": "test"}]

    def test_json_number_string(self):
        """JSON 파싱 결과가 숫자인 경우 리스트로 감싸기"""
        result = _parse_json_field("42")
        assert result == ["42"]

    def test_csv_string(self):
        """쉼표로 구분된 비-JSON 문자열"""
        result = _parse_json_field("AI, 빅데이터, 클라우드")
        assert result == ["AI", "빅데이터", "클라우드"]

    def test_single_string(self):
        """단일 비-JSON 문자열은 리스트로 감싸기"""
        result = _parse_json_field("단일 키워드")
        assert result == ["단일 키워드"]

    def test_multiline_string(self):
        """줄바꿈으로 구분된 문자열"""
        result = _parse_json_field("AI\n빅데이터\n클라우드")
        assert result == ["AI", "빅데이터", "클라우드"]

    def test_return_type_always_list(self):
        """모든 입력에 대해 반환 타입이 list인지 확인"""
        test_cases = [
            None, "", "  ", "test", "a,b,c",
            '["x"]', '{"k":"v"}', "42",
            [], ["a"], {"k": "v"},
        ]
        for case in test_cases:
            result = _parse_json_field(case)
            assert isinstance(result, list), f"Input {case!r} returned {type(result)}"


class TestDumpJsonField:
    """_dump_json_field 테스트"""

    def test_none(self):
        assert _dump_json_field(None) == "[]"

    def test_string_passthrough(self):
        assert _dump_json_field("hello") == "hello"

    def test_list_serialization(self):
        result = _dump_json_field(["AI", "빅데이터"])
        assert json.loads(result) == ["AI", "빅데이터"]


class TestTimestamp:
    """타임스탬프 파싱/포맷 테스트"""

    def test_parse_iso_format(self):
        from datetime import datetime

        result = _parse_timestamp("2024-01-15 09:00:00")
        assert result == datetime(2024, 1, 15, 9, 0, 0)

    def test_parse_date_only(self):
        from datetime import datetime

        result = _parse_timestamp("2024-01-15")
        assert result == datetime(2024, 1, 15)

    def test_parse_none(self):
        assert _parse_timestamp(None) is None

    def test_parse_datetime_passthrough(self):
        from datetime import datetime

        dt = datetime(2024, 1, 15)
        assert _parse_timestamp(dt) is dt

    def test_format_datetime(self):
        from datetime import datetime

        dt = datetime(2024, 1, 15, 9, 30, 0)
        assert _format_timestamp(dt) == "2024-01-15 09:30:00"

    def test_format_none(self):
        assert _format_timestamp(None) is None


class TestBidAnnouncement:
    """BidAnnouncement 모델 테스트"""

    def test_from_dict_roundtrip(self, sample_bid_dict):
        bid = BidAnnouncement.from_dict(sample_bid_dict)
        result = bid.to_dict()

        assert result["bid_ntce_no"] == "20240101001"
        assert result["title"] == "2024년 AI 기반 데이터 분석 시스템 구축"
        assert result["org_name"] == "서울특별시"
        assert result["budget"] == 500000000

    def test_from_api_format(self, sample_bid_api_response):
        """공공데이터포털 API camelCase → snake_case 변환"""
        items = sample_bid_api_response["response"]["body"]["items"]
        bid = BidAnnouncement.from_dict(items[0])

        assert bid.bid_ntce_no == "20240101001"
        assert bid.title == "2024년 AI 기반 데이터 분석 시스템 구축"
        assert bid.org_name == "서울특별시"

    def test_empty_dict(self):
        bid = BidAnnouncement.from_dict({})
        assert bid.bid_ntce_no == ""
        assert bid.title == ""
        assert bid.budget is None


class TestAwardInfo:
    """AwardInfo 모델 테스트"""

    def test_from_dict_roundtrip(self, sample_award_dict):
        award = AwardInfo.from_dict(sample_award_dict)
        result = award.to_dict()

        assert result["winner_name"] == "에이아이테크"
        assert result["award_amount"] == 450000000
        assert result["bid_rate"] == 89.5

    def test_type_conversion(self):
        """문자열 금액/비율이 숫자로 변환되는지 확인"""
        data = {
            "award_amount": "450000000",
            "bid_rate": "89.5",
            "budget": "500000000",
        }
        award = AwardInfo.from_dict(data)
        assert award.award_amount == 450000000
        assert award.bid_rate == 89.5
        assert award.budget == 500000000

    def test_invalid_numbers(self):
        """유효하지 않은 숫자 문자열 처리"""
        data = {
            "award_amount": "invalid",
            "bid_rate": "not_a_number",
        }
        award = AwardInfo.from_dict(data)
        assert award.award_amount is None
        assert award.bid_rate is None


class TestBusinessProfile:
    """BusinessProfile 모델 테스트"""

    def test_from_dict_roundtrip(self, sample_business_profile_dict):
        profile = BusinessProfile.from_dict(sample_business_profile_dict)

        assert profile.company_name == "테스트 IT솔루션"
        assert profile.business_types == ["SW개발", "AI", "데이터분석"]
        assert profile.min_budget == 100000000

        # to_dict 후 JSON 필드가 문자열로 직렬화되는지 확인
        result = profile.to_dict()
        assert isinstance(result["business_types"], str)
        assert json.loads(result["business_types"]) == ["SW개발", "AI", "데이터분석"]

    def test_json_field_from_string(self):
        """JSON 문자열로 저장된 필드가 올바르게 파싱되는지"""
        data = {
            "biz_id": "test",
            "company_name": "테스트",
            "business_types": '["SW개발", "AI"]',
            "licenses": '["소프트웨어사업자"]',
        }
        profile = BusinessProfile.from_dict(data)
        assert profile.business_types == ["SW개발", "AI"]
        assert profile.licenses == ["소프트웨어사업자"]


class TestNewsArticle:
    """NewsArticle 모델 테스트"""

    def test_from_dict_roundtrip(self, sample_news_dict):
        """from_dict → to_dict 라운드트립 테스트"""
        article = NewsArticle.from_dict(sample_news_dict)
        result = article.to_dict()

        assert result["title"] == "서울시, AI 기반 행정 서비스 확대 추진"
        assert result["link"] == "https://example.com/news/12345"
        assert result["pub_date"] == "2024-01-10"
        assert result["search_query"] == "서울특별시 AI"

    def test_empty_dict(self):
        """빈 딕셔너리로 생성"""
        article = NewsArticle.from_dict({})
        assert article.title is None
        assert article.link is None
        assert article.pub_date is None

    def test_pub_date_camel_case(self):
        """pubDate (camelCase) 필드 매핑 테스트"""
        data = {
            "title": "테스트 기사",
            "pubDate": "2024-03-15",
        }
        article = NewsArticle.from_dict(data)
        assert article.pub_date == "2024-03-15"

    def test_to_dict_preserves_fields(self):
        """to_dict가 모든 필드를 보존하는지"""
        data = {
            "id": 1,
            "title": "테스트",
            "description": "설명",
            "link": "https://example.com",
            "pub_date": "2024-01-01",
            "search_query": "검색어",
            "related_bid_no": "20240001",
        }
        article = NewsArticle.from_dict(data)
        result = article.to_dict()
        assert result["id"] == 1
        assert result["related_bid_no"] == "20240001"


class TestAnalysisResult:
    """AnalysisResult 모델 테스트"""

    def test_from_dict_roundtrip(self):
        """from_dict → to_dict 라운드트립 테스트"""
        data = {
            "bid_ntce_no": "20240101001",
            "biz_id": "1234567890",
            "relevance_score": 85.5,
            "match_score": 72.0,
            "summary": "AI 기반 시스템 구축 사업",
            "strategy_report": "전략 보고서 내용",
            "competitors": ["경쟁사A", "경쟁사B"],
        }
        result_obj = AnalysisResult.from_dict(data)
        result = result_obj.to_dict()

        assert result["bid_ntce_no"] == "20240101001"
        assert result["relevance_score"] == 85.5
        assert result["match_score"] == 72.0
        assert result["summary"] == "AI 기반 시스템 구축 사업"

    def test_empty_dict(self):
        """빈 딕셔너리로 생성"""
        result_obj = AnalysisResult.from_dict({})
        assert result_obj.bid_ntce_no is None
        assert result_obj.relevance_score is None
        assert result_obj.competitors == []

    def test_score_type_conversion(self):
        """문자열 점수가 float로 변환되는지"""
        data = {
            "relevance_score": "92.5",
            "match_score": "80",
        }
        result_obj = AnalysisResult.from_dict(data)
        assert result_obj.relevance_score == 92.5
        assert result_obj.match_score == 80.0

    def test_invalid_score(self):
        """유효하지 않은 점수 문자열"""
        data = {
            "relevance_score": "invalid",
            "match_score": "not_a_number",
        }
        result_obj = AnalysisResult.from_dict(data)
        assert result_obj.relevance_score is None
        assert result_obj.match_score is None

    def test_competitors_json_string(self):
        """competitors가 JSON 문자열로 저장된 경우"""
        data = {
            "competitors": '["회사A", "회사B", "회사C"]',
        }
        result_obj = AnalysisResult.from_dict(data)
        assert result_obj.competitors == ["회사A", "회사B", "회사C"]

