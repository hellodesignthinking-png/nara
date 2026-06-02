"""
공유 헬퍼 함수 모듈

routes 패키지 내 모든 라우트 모듈이 공통으로 사용하는
DB 접근, 변환 함수, 설정 로드/저장 유틸리티를 제공합니다.
"""

import json
import logging
from datetime import datetime
from pathlib import Path

from src.api.utils import biz_profile_to_matcher_dict, bid_to_matcher_dict
from src.config import load_config
from src.models.database import DatabaseManager
from src.models.schemas import (
    BusinessProfile,
    BidAnnouncement,
    AnalysisResult,
    _parse_json_field,
)

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# DB 헬퍼
# ──────────────────────────────────────────────


def _get_db() -> DatabaseManager:
    """
    DatabaseManager 인스턴스를 생성하고 연결합니다.

    레거시 호출부 호환을 위해 유지됩니다.
    새 엔드포인트에서는 get_db()를 Depends로 사용하세요.
    """
    db = DatabaseManager()
    db.connect()
    return db


def get_db():
    """
    FastAPI 의존성 주입용 DB Generator.

    사용 예:
        @router.get("/example")
        async def example(db: DatabaseManager = Depends(get_db)):
            ...

    Generator 패턴으로 요청 종료 시 자동으로 close()가 호출됩니다.
    """
    db = DatabaseManager()
    db.connect()
    try:
        yield db
    finally:
        db.close()


# ──────────────────────────────────────────────
# 변환 함수
# ──────────────────────────────────────────────


def _business_profile_to_api_dict(profile: BusinessProfile) -> dict:
    """
    BusinessProfile 객체를 API 응답용 딕셔너리로 변환합니다.

    DB 저장 시 JSON 문자열로 직렬화되는 필드들을
    파싱된 리스트 형태로 반환하여 클라이언트가 바로 사용할 수 있도록 합니다.
    """
    return {
        "biz_id": profile.biz_id,
        "company_name": profile.company_name,
        "ceo_name": profile.ceo_name,
        "business_types": profile.business_types,       # 파싱된 리스트
        "licenses": profile.licenses,                    # 파싱된 리스트
        "regions": profile.regions,                      # 파싱된 리스트
        "past_projects": profile.past_projects,          # 파싱된 리스트
        "annual_revenue": profile.annual_revenue,
        "employee_count": profile.employee_count,
        "keywords": profile.keywords,                    # 파싱된 리스트
        "min_budget": profile.min_budget,
        "max_budget": profile.max_budget,
        "created_at": profile.created_at.strftime("%Y-%m-%d %H:%M:%S") if profile.created_at else None,
        "updated_at": profile.updated_at.strftime("%Y-%m-%d %H:%M:%S") if profile.updated_at else None,
    }


def _analysis_to_api_dict(result: AnalysisResult) -> dict:
    """AnalysisResult 객체를 API 응답용 딕셔너리로 변환합니다."""
    return {
        "id": result.id,
        "bid_ntce_no": result.bid_ntce_no,
        "biz_id": result.biz_id,
        "relevance_score": result.relevance_score,
        "match_score": result.match_score,
        "summary": result.summary,
        "strategy_report": result.strategy_report,
        "competitors": result.competitors,               # 파싱된 리스트
        "analyzed_at": result.analyzed_at.strftime("%Y-%m-%d %H:%M:%S") if result.analyzed_at else None,
    }


def _bid_to_api_dict(bid: BidAnnouncement) -> dict:
    """BidAnnouncement 객체를 API 응답용 딕셔너리로 변환합니다."""
    return {
        "bid_ntce_no": bid.bid_ntce_no,
        "bid_ntce_ord": bid.bid_ntce_ord,
        "title": bid.title,
        "org_name": bid.org_name,
        "demand_org_name": bid.demand_org_name,
        "budget": bid.budget,
        "bid_begin_dt": bid.bid_begin_dt,
        "bid_close_dt": bid.bid_close_dt,
        "category": bid.category,
        "bid_method": bid.bid_method,
        "contract_method": bid.contract_method,
        "region": bid.region,
        "license_limit": bid.license_limit,
        "rfp_url": bid.rfp_url,
        "rfp_text": bid.rfp_text,
        "collected_at": bid.collected_at.strftime("%Y-%m-%d %H:%M:%S") if bid.collected_at else None,
    }


# utils.py로 추출된 변환 함수의 하위 호환 래퍼
_biz_profile_to_matcher_dict = biz_profile_to_matcher_dict
_bid_to_matcher_dict = bid_to_matcher_dict


# ──────────────────────────────────────────────
# Settings JSON 파일 기반 관리
# ──────────────────────────────────────────────

def _get_settings_path() -> Path:
    """Config에서 settings.json 경로를 가져옵니다."""
    return load_config().settings_path


def _load_settings() -> dict:
    """data/settings.json에서 사용자 설정을 로드합니다."""
    settings_path = _get_settings_path()
    if settings_path.exists():
        try:
            with open(settings_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _save_settings(settings: dict) -> None:
    """사용자 설정을 data/settings.json에 저장합니다."""
    settings_path = _get_settings_path()
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    with open(settings_path, "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)


# ──────────────────────────────────────────────
# 공통 유틸리티 함수
# ──────────────────────────────────────────────


def _extract_requirements(title: str, description: str, bid: dict) -> list[str]:
    """공고에서 필수요건(자격/면허/지역제한 등)을 추출합니다."""
    reqs = []
    text = f"{title} {description}"

    # 면허/자격 키워드
    license_kw = [
        "소프트웨어사업자", "정보통신공사업", "전기공사업", "건축사사무소",
        "엔지니어링", "기술사", "감리", "보안업체", "ISMS", "ISO",
    ]
    for lk in license_kw:
        if lk in text:
            reqs.append(f"📜 {lk}")

    # 지역제한
    regions = ["서울", "경기", "부산", "대구", "인천", "광주", "대전", "울산", "세종",
               "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주"]
    region_match = bid.get("region", "")
    # 시스템 기본값은 무시
    if region_match and ("조달청" in region_match or "나라장터" in region_match or "자체" in region_match):
        region_match = ""
    if not region_match:
        for r in regions:
            if f"{r}제한" in text or f"{r}지역" in text or f"{r}소재" in text:
                region_match = r
                break
    if region_match:
        reqs.append(f"📍 {region_match} 지역제한")

    # 예산 규모
    budget = bid.get("budget") or bid.get("presmptPrce")
    if budget and isinstance(budget, (int, float)) and budget > 0:
        if budget >= 100000000:  # 1억 이상
            reqs.append(f"💰 {budget/100000000:.1f}억 이상 실적")

    # 중소기업/여성기업
    if "중소기업" in text:
        reqs.append("🏷️ 중소기업 제한")
    if "여성기업" in text:
        reqs.append("🏷️ 여성기업 우대")
    if "사회적기업" in text:
        reqs.append("🏷️ 사회적기업")

    return reqs if reqs else ["ℹ️ 별도 자격제한 없음"]


def _calc_days_left(close_dt: str) -> int:
    """마감일까지 남은 일수를 계산합니다."""
    if not close_dt:
        return 999
    try:
        # 다양한 날짜 형식 처리
        close_str = close_dt.replace("-", "").replace("/", "").replace(" ", "")[:8]
        close_date = datetime.strptime(close_str, "%Y%m%d")
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        return max(0, (close_date - today).days)
    except Exception:
        return 999
