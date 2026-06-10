"""
NARA Analyzer 커스텀 예외 모듈

모든 예외는 NaraError를 상속하여 일관된 에러 처리를 제공합니다.
"""


class NaraError(Exception):
    """NARA Analyzer 기본 예외 클래스"""
    pass


class APIError(NaraError):
    """외부 API 호출 중 발생한 에러"""
    def __init__(self, message: str, status_code: int = 0, api_name: str = ""):
        self.status_code = status_code
        self.api_name = api_name
        super().__init__(f"[{api_name}] {message}" if api_name else message)


class RateLimitError(APIError):
    """API 호출 한도 초과 에러"""
    def __init__(self, api_name: str = "", retry_after: int = 0):
        self.retry_after = retry_after
        msg = f"호출 한도 초과{f' (재시도: {retry_after}초 후)' if retry_after else ''}"
        super().__init__(msg, status_code=429, api_name=api_name)


class ParseError(NaraError):
    """데이터 파싱 중 발생한 에러 (JSON, XML, HWP, PDF 등)"""
    pass


class ConfigError(NaraError):
    """설정 관련 에러 (누락된 키, 잘못된 값 등)"""
    pass


class DatabaseError(NaraError):
    """데이터베이스 작업 중 발생한 에러"""
    pass


class LLMError(NaraError):
    """LLM 분석 중 발생한 에러 (API 호출 실패, 응답 파싱 실패 등)"""
    pass


class CollectionError(NaraError):
    """데이터 수집 중 발생한 에러"""
    pass


class ReporterError(NaraError):
    """리포터 관련 에러 (이메일/Slack 전송 실패 등)"""
    pass
