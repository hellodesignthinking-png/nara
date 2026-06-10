"""
데이터 변환 유틸리티

다양한 데이터 모델 간 변환 함수를 제공합니다.
main.py와 API 라우트에서 공통으로 사용합니다.
"""

from typing import Any, Union

from src.models.schemas import BusinessProfile


def biz_profile_to_matcher_dict(profile: BusinessProfile) -> dict:
    """
    BusinessProfile dataclass를 BizMatcher가 기대하는 dict 형태로 변환합니다.

    main.py의 동일 함수를 참조하되, API 내부에서 독립적으로 사용합니다.
    """
    return {
        "biz_id": profile.biz_id,
        "name": profile.company_name,
        "company_name": profile.company_name,
        "business_types": profile.business_types,
        "licenses": profile.licenses,
        "regions": profile.regions,
        "region": profile.regions[0] if profile.regions else "",
        "past_projects": [
            {"name": p} if isinstance(p, str) else p
            for p in profile.past_projects
        ],
        "budget_range": {
            "min": profile.min_budget or 0,
            "max": profile.max_budget if profile.max_budget is not None else 999999999999,
        },
        "keywords": profile.keywords,
        "annual_revenue": profile.annual_revenue,
        "employee_count": profile.employee_count,
    }


def bid_to_matcher_dict(bid: Union[Any, dict]) -> dict:
    """
    BidAnnouncement dataclass를 BizMatcher/LLM이 기대하는 dict 형태로 변환합니다.

    main.py의 동일 함수를 참조합니다.
    """
    if isinstance(bid, dict):
        return bid
    return {
        "bid_ntce_no": bid.bid_ntce_no,
        "title": bid.title,
        "bidNtceNm": bid.title,
        "org_name": bid.org_name,
        "ntceInsttNm": bid.org_name,
        "dminstt_nm": bid.demand_org_name,
        "budget": bid.budget,
        "presmptPrce": bid.budget,
        "category": bid.category,
        "region": bid.region,
        "required_licenses": [bid.license_limit] if bid.license_limit else [],
        "license_limit": bid.license_limit,
        "bid_close_dt": bid.bid_close_dt,
        "bidClseDt": bid.bid_close_dt,
        "rfp_url": bid.rfp_url,
        "rfp_text": bid.rfp_text or "",
        "description": bid.rfp_text or "",
    }
