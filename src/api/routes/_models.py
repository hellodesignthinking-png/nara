"""
Pydantic 요청/응답 모델

routes 패키지 내 라우트 모듈에서 사용하는
모든 Pydantic 요청/응답 모델을 정의합니다.
"""

from typing import Optional

from pydantic import BaseModel, Field


class BusinessCreateRequest(BaseModel):
    """사업자 등록/수정 요청 본문"""
    biz_id: str = Field(..., description="사업자등록번호")
    company_name: str = Field(..., description="회사명")
    ceo_name: Optional[str] = Field(None, description="대표자명")
    business_types: list[str] = Field(default_factory=list, description="업종 목록")
    licenses: list[str] = Field(default_factory=list, description="보유 면허/자격")
    regions: list[str] = Field(default_factory=list, description="활동 가능 지역")
    keywords: list[str] = Field(default_factory=list, description="관심 키워드")
    past_projects: list[str] = Field(default_factory=list, description="과거 수행실적")
    annual_revenue: Optional[int] = Field(None, description="연매출(원)")
    employee_count: Optional[int] = Field(None, description="직원 수")
    min_budget: Optional[int] = Field(None, description="최소 예산(원)")
    max_budget: Optional[int] = Field(None, description="최대 예산(원)")


class BidCollectRequest(BaseModel):
    """공고 수집 요청 본문"""
    start_date: Optional[str] = Field(None, description="시작일 (YYYYMMDD)")
    end_date: Optional[str] = Field(None, description="종료일 (YYYYMMDD)")
    keyword: Optional[str] = Field(None, description="검색 키워드 (공고명 검색)")


class StrategyAnalysisRequest(BaseModel):
    """실시간 전략 분석 요청 본문"""
    bid_ntce_no: str = Field(..., description="분석할 공고번호")


class ProposalStrategyRequest(BaseModel):
    """제안서 고도화 전략 분석 요청 본문"""
    bid_ntce_no: str = Field(..., description="분석할 공고번호")
    biz_id: Optional[str] = Field(None, description="매칭할 사업자 ID (미지정 시 자동 선택)")


class KeywordsUpdateRequest(BaseModel):
    """키워드 업데이트 요청"""
    keywords: list[str] = Field(..., description="관심 키워드 목록")
    exclude_keywords: list[str] = Field(default_factory=list, description="제외 키워드 목록")


class RelevanceUpdateRequest(BaseModel):
    """관련도 설정 업데이트 요청"""
    min_relevance_score: int = Field(..., ge=0, le=100, description="최소 관련도 점수")


class ScheduleUpdateRequest(BaseModel):
    """스케줄 변경 요청"""
    hour: int = Field(..., ge=0, le=23, description="실행 시각 (시)")
    minute: int = Field(default=0, ge=0, le=59, description="실행 시각 (분)")


class SlackWebhookRequest(BaseModel):
    """Slack 웹훅 URL 설정 요청"""
    webhook_url: str = Field(..., description="Slack Incoming Webhook URL")
