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
    credit_rating: Optional[str] = Field("BBB", description="신용평가등급")
    company_type: Optional[str] = Field(None, description="기업 구분")
    has_sanctions: Optional[bool] = Field(False, description="제재 이력 여부")
    is_shared: Optional[bool] = Field(False, description="회사 정보 공유 여부")
    website_url: Optional[str] = Field(None, description="홈페이지 URL")
    intro_file_url: Optional[str] = Field(None, description="회사소개서 경로")
    social_links: Optional[str] = Field(None, description="소셜 네트워크 링크")



class BidCollectRequest(BaseModel):
    """공고 수집 요청 본문"""
    start_date: Optional[str] = Field(None, description="시작일 (YYYYMMDD)")
    end_date: Optional[str] = Field(None, description="종료일 (YYYYMMDD)")
    keyword: Optional[str] = Field(None, description="검색 키워드 (공고명 검색)")
    platforms: list[str] = Field(default_factory=list, description="수집 대상 플랫폼 목록 (예: nara, kstartup, samgov, ungm)")


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


class AnalysisChatRequest(BaseModel):
    """AI 전략 Q&A 대화 요청 본문"""
    bid_ntce_no: str = Field(..., description="공고번호")
    biz_id: str = Field(..., description="사업자등록번호")
    message: str = Field(..., description="사용자 질문 메시지")
    chat_history: list[dict] = Field(default_factory=list, description="이전 대화 기록")


class ApiKeyTestRequest(BaseModel):
    """API 키 연결 테스트 요청"""
    api_name: str = Field(..., description="API 종류 (data_go_kr, naver, openai, gemini)")
    api_key: str = Field(..., description="API Key 값")
    api_secret: Optional[str] = Field(None, description="API Secret 값 (네이버 등에 필요)")


class MemberAddRequest(BaseModel):
    """직원 추가 요청 본문"""
    username: str = Field(..., description="추가할 유저 ID")
    role: str = Field("member", description="역할 (admin, member 등)")


class MemberRoleUpdateRequest(BaseModel):
    """직원 역할 수정 요청 본문"""
    role: str = Field(..., description="변경할 역할 (admin, member 등)")


class AISettingsUpdateRequest(BaseModel):
    """개인 AI 에이전트 가중치 및 설정 요청 본문"""
    bid_target: str = Field("stable", description="관심 입찰 목표")
    relevance_weight: float = Field(0.35, ge=0.0, le=1.0, description="키워드/업종 가중치")
    capacity_weight: float = Field(0.35, ge=0.0, le=1.0, description="예산/실적 가중치")
    credit_weight: float = Field(0.30, ge=0.0, le=1.0, description="신용/가점 가중치")
    ai_persona: str = Field("strategic", description="AI 에이전트 페르소나")
    custom_keywords: list[str] = Field(default_factory=list, description="개인 맞춤 키워드")


class AdminRoleUpdateRequest(BaseModel):
    """관리자 권한 변경 요청 본문"""
    is_admin: bool = Field(..., description="관리자 여부 플래그")


class CafePostCreateRequest(BaseModel):
    """사내 카페 게시글 작성 요청 본문"""
    title: str = Field(..., description="게시글 제목")
    content: str = Field(..., description="게시글 내용")


class CafeCommentCreateRequest(BaseModel):
    """사내 카페 댓글 작성 요청 본문"""
    content: str = Field(..., description="댓글 내용")


class CollaborationProposalCreateRequest(BaseModel):
    """공동 수급/협업 제안 생성 요청 본문"""
    sender_biz_id: str = Field(..., description="제안을 보내는 내 회사 사업자등록번호")
    receiver_biz_id: str = Field(..., description="제안을 받는 상대 회사 사업자등록번호")
    bid_ntce_no: str = Field(..., description="대상 공고번호")
    message: str = Field("", description="제안 메시지")


class CollaborationStatusUpdateRequest(BaseModel):
    """협업 제안 상태 변경 요청 본문"""
    status: str = Field(..., description="변경할 상태 (accepted 또는 rejected)")


class CollaborationAiDraftRequest(BaseModel):
    """공동 수급/협업 제안 AI 초안 생성 요청 본문"""
    sender_biz_id: str = Field(..., description="제안 송신 사업자번호")
    receiver_biz_id: str = Field(..., description="제안 수신 사업자번호")
    bid_ntce_no: str = Field(..., description="대상 공고번호")



