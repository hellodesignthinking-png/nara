"""
Config 모듈 테스트

설정 로드, 검증, 기본값 등을 테스트합니다.
"""

import os
import pytest
from unittest.mock import patch

from src.utils.exceptions import ConfigError

from src.config import Config, _safe_int


class TestConfig:
    """Config dataclass 테스트"""

    def test_default_values(self):
        """기본값이 올바르게 설정되는지"""
        config = Config()
        assert config.data_go_kr_api_key == ""
        assert config.llm_engine == "gemini"
        assert config.openai_model == "gpt-4o"
        assert config.gemini_model == "gemini-2.5-flash"
        assert config.min_relevance_score == 40
        assert config.past_years == 2

    def test_validate_all_missing(self):
        """모든 키가 비어있을 때 ConfigError 발생"""
        config = Config()
        with pytest.raises(ConfigError):
            config.validate()

    def test_validate_gemini_mode(self):
        """Gemini 모드에서 gemini 키 미설정 경고"""
        config = Config(
            data_go_kr_api_key="key",
            llm_engine="gemini",
            gemini_api_key="",
        )
        warnings = config.validate()
        assert any("GEMINI" in w for w in warnings)

    def test_validate_openai_mode(self):
        """OpenAI 모드에서 openai 키 미설정 경고"""
        config = Config(
            data_go_kr_api_key="key",
            llm_engine="openai",
            openai_api_key="",
        )
        warnings = config.validate()
        assert any("OPENAI" in w for w in warnings)

    def test_validate_all_set(self):
        """모든 필수 키가 설정된 경우"""
        config = Config(
            data_go_kr_api_key="key",
            naver_client_id="id",
            naver_client_secret="secret",
            llm_engine="gemini",
            gemini_api_key="gkey",
        )
        warnings = config.validate()
        assert len(warnings) == 0

    def test_repr_masks_keys(self):
        """__repr__에서 API 키가 마스킹되는지"""
        config = Config(
            openai_api_key="sk-1234567890abcdef",
            gemini_api_key="AIza-xyz",
        )
        repr_str = repr(config)
        assert "sk-1234567890abcdef" not in repr_str
        assert "AIza-xyz" not in repr_str
        assert "****" in repr_str


class TestSafeInt:
    """_safe_int 헬퍼 함수 테스트"""

    def test_valid_int(self):
        assert _safe_int("42", 0) == 42

    def test_invalid_string(self):
        assert _safe_int("abc", 99) == 99

    def test_none(self):
        assert _safe_int(None, 10) == 10

    def test_empty_string(self):
        assert _safe_int("", 5) == 5
