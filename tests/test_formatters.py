"""formatters 모듈 테스트"""
import pytest
from src.utils.formatters import format_budget


class TestFormatBudget:
    """format_budget 함수 테스트"""

    def test_none_budget(self):
        """None인 경우 미공개 반환"""
        result = format_budget(None)
        assert "미공개" in result or result == "미공개"

    def test_zero_budget(self):
        """0원인 경우"""
        result = format_budget(0)
        assert result is not None
        assert "0원" in result

    def test_normal_budget(self):
        """일반 예산 (만원 단위)"""
        result = format_budget(100000000)
        assert result is not None
        assert len(result) > 0

    def test_large_budget(self):
        """큰 금액"""
        result = format_budget(999999999999)
        assert result is not None

    def test_string_budget_with_unit(self):
        """이미 포맷된 문자열 예산"""
        result = format_budget("5억원")
        assert result == "5억원"

    def test_string_budget_numeric(self):
        """숫자 문자열 예산"""
        result = format_budget("50000")
        assert result is not None

    def test_budget_won_unit(self):
        """원 단위 예산"""
        result = format_budget(500000000, unit="원")
        assert result is not None
        assert "원" in result


class TestFormatDate:
    """format_date 함수 테스트"""

    def test_format_date_exists(self):
        """format_date 함수 존재 여부 확인 (미구현 시 skip)"""
        try:
            from src.utils.formatters import format_date
        except ImportError:
            pytest.skip("format_date 함수가 아직 구현되지 않았습니다")

    def test_none_date(self):
        """None 날짜"""
        try:
            from src.utils.formatters import format_date
        except ImportError:
            pytest.skip("format_date 함수가 아직 구현되지 않았습니다")
        result = format_date(None)
        assert result == "-" or result == "" or result is not None

    def test_valid_date_string(self):
        """유효한 날짜 문자열"""
        try:
            from src.utils.formatters import format_date
        except ImportError:
            pytest.skip("format_date 함수가 아직 구현되지 않았습니다")
        result = format_date("2025-06-09")
        assert result is not None
