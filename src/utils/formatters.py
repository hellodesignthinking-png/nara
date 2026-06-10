"""
공통 포맷팅 유틸리티 모듈

프로젝트 전반에서 사용되는 예산 포맷, 공고 데이터 정규화 등
공통 함수를 제공합니다.

기존에 cli_reporter, email_reporter, slack_reporter에 각각 복제되어 있던
_format_budget() 함수를 통합하고, 단위 불일치(만원 vs 원)를 해소합니다.
"""

from typing import Any


def format_budget(budget: Any, unit: str = "만원") -> str:
    """
    예산을 가독성 좋은 형식으로 포맷합니다.

    Args:
        budget: 예산 값 (int, float, str 등)
        unit: 입력 데이터의 단위.
            - "만원": 입력값이 만원 단위 (예: 50000 → 5.0억원)
            - "원": 입력값이 원 단위 (예: 500000000 → 5.0억원)

    Returns:
        포맷된 예산 문자열 (예: "5.0억원", "3,000만원")
    """
    if budget is None:
        return "미공개"

    if isinstance(budget, str):
        # 이미 포맷된 문자열이면 그대로 반환
        if "원" in budget or "만" in budget or "억" in budget:
            return budget
        try:
            budget = float(budget.replace(",", ""))
        except ValueError:
            return budget

    if isinstance(budget, (int, float)):
        if unit == "원":
            # 원 단위 → 만원 단위로 변환 후 처리
            budget = budget / 10000

        # 만원 단위 기준 포맷
        if budget >= 10000:
            # 억원 단위로 변환
            billions = budget / 10000
            return f"{billions:,.1f}억원"
        elif budget >= 1:
            return f"{budget:,.0f}만원"
        elif budget > 0:
            return f"{budget * 10000:,.0f}원"
        else:
            return "0원"

    return str(budget)


def safe_float(value: Any, default: float = 0.0) -> float:
    """값을 안전하게 float로 변환합니다. inf/NaN은 기본값으로 대체합니다."""
    if value is None:
        return default
    try:
        result = float(value)
        if result != result or result == float("inf") or result == float("-inf"):
            return default
        return result
    except (ValueError, TypeError):
        return default

