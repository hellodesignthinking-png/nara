"""
BidCollector API 응답 파싱 테스트

실제 API 호출 없이 _parse_response() 로직을 다양한 케이스로 검증합니다.
"""

import pytest
from datetime import datetime
from unittest.mock import MagicMock

from src.collectors.bid_collector import BidCollector
from src.models.schemas import BidAnnouncement


@pytest.fixture
def collector():
    """API 키만 설정된 BidCollector 인스턴스"""
    config = MagicMock()
    config.data_go_kr_api_key = "test_key"
    return BidCollector(config)


class TestParseResponse:
    """_parse_response 응답 파싱 테스트"""

    def test_normal_response(self, collector, sample_bid_api_response):
        """정상적인 API 응답 파싱"""
        bids, total = collector._parse_response(sample_bid_api_response)
        assert total == 2
        assert len(bids) == 2
        assert isinstance(bids[0], BidAnnouncement)
        assert bids[0].bid_ntce_no == "20240101001"
        assert bids[0].title == "2024년 AI 기반 데이터 분석 시스템 구축"

    def test_empty_response(self, collector):
        """결과 없는 API 응답"""
        data = {
            "response": {
                "header": {"resultCode": "00", "resultMsg": "NORMAL SERVICE"},
                "body": {"items": [], "totalCount": 0},
            }
        }
        bids, total = collector._parse_response(data)
        assert total == 0
        assert len(bids) == 0

    def test_error_response(self, collector):
        """에러 응답 처리"""
        data = {
            "response": {
                "header": {"resultCode": "99", "resultMsg": "INVALID KEY"},
                "body": {},
            }
        }
        with pytest.raises(ValueError, match="API 오류 응답"):
            collector._parse_response(data)

    def test_single_item_as_dict(self, collector):
        """단건 응답이 dict로 오는 경우 (리스트가 아닌)"""
        data = {
            "response": {
                "header": {"resultCode": "00"},
                "body": {
                    "items": {
                        "item": {
                            "bidNtceNo": "SINGLE001",
                            "bidNtceNm": "단건 공고",
                        }
                    },
                    "totalCount": 1,
                },
            }
        }
        bids, total = collector._parse_response(data)
        assert total == 1
        assert len(bids) == 1
        assert bids[0].bid_ntce_no == "SINGLE001"

    def test_budget_type_conversion(self, collector):
        """추정가격 문자열 → 정수 변환"""
        data = {
            "response": {
                "header": {"resultCode": "00"},
                "body": {
                    "items": [
                        {
                            "bidNtceNo": "B001",
                            "bidNtceNm": "테스트",
                            "presmptPrce": "500000000",
                        }
                    ],
                    "totalCount": 1,
                },
            }
        }
        bids, total = collector._parse_response(data)
        assert bids[0].budget == 500000000

    def test_malformed_item_skipped(self, collector):
        """필수 필드 누락 아이템도 안전하게 처리"""
        data = {
            "response": {
                "header": {"resultCode": "00"},
                "body": {
                    "items": [
                        {
                            "bidNtceNo": "GOOD001",
                            "bidNtceNm": "정상 공고",
                        },
                        {
                            # bidNtceNo 누락 — from_dict에서 빈 문자열로 처리됨
                            "bidNtceNm": "비정상 공고",
                            "presmptPrce": "invalid_number",
                        },
                    ],
                    "totalCount": 2,
                },
            }
        }
        bids, total = collector._parse_response(data)
        assert total == 2
        assert len(bids) >= 1  # 파싱 가능한 아이템은 포함


class TestCollectorLifecycle:
    """Collector 생명주기 테스트"""

    def test_context_manager(self):
        config = MagicMock()
        config.data_go_kr_api_key = "test"
        with BidCollector(config) as collector:
            assert collector.session is not None
        assert collector.session is None

    def test_close_idempotent(self, collector):
        """close()를 여러 번 호출해도 안전"""
        collector.close()
        collector.close()  # 두 번째 호출 시 에러 없어야 함
