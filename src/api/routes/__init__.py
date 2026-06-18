"""
API 라우트 패키지

나라장터 자동 분석 시스템의 모든 REST API 엔드포인트를 모듈별로 분리합니다.

엔드포인트 그룹:
  - /api/dashboard  : 대시보드 통계 및 최근 분석 결과
  - /api/businesses : 사업자 프로필 CRUD
  - /api/bids       : 입찰공고 조회 및 수집 트리거
  - /api/analyze    : 전체 분석 파이프라인 실행
  - /api/analyses   : 분석 결과 조회
  - /api/settings   : 시스템 설정 조회
  - /api/news       : 기관별 뉴스 조회
"""

from fastapi import APIRouter

from .dashboard import router as dashboard_router
from .bids import router as bids_router
from .businesses import router as businesses_router
from .analyses import router as analyses_router
from .settings import router as settings_router
from .documents import router as documents_router
from .auth import router as auth_router
from .favorites import router as favorites_router
from .admin import router as admin_router
from .policies import router as policies_router
from .proposals import router as proposals_router


def create_main_router() -> APIRouter:
    """모든 하위 라우터를 결합한 메인 API 라우터를 생성합니다."""
    main = APIRouter(prefix="/api", tags=["api"])
    main.include_router(auth_router)
    main.include_router(favorites_router)
    main.include_router(admin_router)
    main.include_router(dashboard_router)
    main.include_router(bids_router)
    main.include_router(businesses_router)
    main.include_router(analyses_router)
    main.include_router(settings_router)
    main.include_router(documents_router)
    main.include_router(policies_router)
    main.include_router(proposals_router)
    return main

