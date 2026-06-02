"""
데이터 모델 스키마 정의 모듈

SQLite 기반 데이터 모델을 dataclass로 정의합니다.
각 모델은 from_dict / to_dict 메서드를 제공하여
딕셔너리 ↔ 객체 간 변환을 지원합니다.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


# ──────────────────────────────────────────────
# 헬퍼 함수
# ──────────────────────────────────────────────

def _parse_json_field(value):
    """JSON 문자열 또는 리스트를 파이썬 리스트로 변환합니다.
    비-JSON 문자열(마크다운 등)은 원본 문자열을 그대로 반환합니다."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return [value]
    if isinstance(value, str):
        if not value.strip():
            return []
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return parsed
            elif isinstance(parsed, dict):
                return [parsed]
            return value  # JSON 파싱 결과가 문자열이면 원본 반환
        except (json.JSONDecodeError, TypeError):
            return value  # 비-JSON 문자열(마크다운 등)은 원본 그대로 반환
    return []


def _dump_json_field(value) -> str:
    """리스트를 JSON 문자열로 직렬화합니다."""
    if value is None:
        return "[]"
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def _parse_timestamp(value) -> Optional[datetime]:
    """문자열 또는 datetime을 datetime 객체로 변환합니다."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        # ISO 형식 파싱 시도
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(value, fmt)
            except ValueError:
                continue
    return None


def _format_timestamp(value) -> Optional[str]:
    """datetime 객체를 문자열로 포맷합니다."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return str(value)


# ──────────────────────────────────────────────
# 사업자 프로필
# ──────────────────────────────────────────────

@dataclass
class BusinessProfile:
    """
    사업자 프로필 모델

    사업자등록번호를 기본키로 사용하며,
    업종·면허·지역 등 매칭에 필요한 사업자 정보를 담고 있습니다.
    """
    biz_id: str                              # 사업자등록번호 (PK)
    company_name: str                        # 회사명
    ceo_name: Optional[str] = None           # 대표자명
    business_types: list = field(default_factory=list)   # 업종 목록
    licenses: list = field(default_factory=list)         # 보유 면허/자격
    regions: list = field(default_factory=list)          # 활동 가능 지역
    past_projects: list = field(default_factory=list)    # 과거 수행실적
    annual_revenue: Optional[int] = None     # 연매출
    employee_count: Optional[int] = None     # 직원 수
    keywords: list = field(default_factory=list)         # 관심 키워드
    min_budget: Optional[int] = None         # 최소 예산
    max_budget: Optional[int] = None         # 최대 예산
    created_at: Optional[datetime] = None    # 생성일시
    updated_at: Optional[datetime] = None    # 수정일시

    @classmethod
    def from_dict(cls, data: dict) -> "BusinessProfile":
        """딕셔너리에서 BusinessProfile 객체를 생성합니다."""
        return cls(
            biz_id=data.get("biz_id", ""),
            company_name=data.get("company_name", ""),
            ceo_name=data.get("ceo_name"),
            business_types=_parse_json_field(data.get("business_types")),
            licenses=_parse_json_field(data.get("licenses")),
            regions=_parse_json_field(data.get("regions")),
            past_projects=_parse_json_field(data.get("past_projects")),
            annual_revenue=data.get("annual_revenue"),
            employee_count=data.get("employee_count"),
            keywords=_parse_json_field(data.get("keywords")),
            min_budget=data.get("min_budget"),
            max_budget=data.get("max_budget"),
            created_at=_parse_timestamp(data.get("created_at")),
            updated_at=_parse_timestamp(data.get("updated_at")),
        )

    def to_dict(self) -> dict:
        """객체를 딕셔너리로 변환합니다. JSON 필드는 문자열로 직렬화됩니다."""
        return {
            "biz_id": self.biz_id,
            "company_name": self.company_name,
            "ceo_name": self.ceo_name,
            "business_types": _dump_json_field(self.business_types),
            "licenses": _dump_json_field(self.licenses),
            "regions": _dump_json_field(self.regions),
            "past_projects": _dump_json_field(self.past_projects),
            "annual_revenue": self.annual_revenue,
            "employee_count": self.employee_count,
            "keywords": _dump_json_field(self.keywords),
            "min_budget": self.min_budget,
            "max_budget": self.max_budget,
            "created_at": _format_timestamp(self.created_at),
            "updated_at": _format_timestamp(self.updated_at),
        }


# ──────────────────────────────────────────────
# 입찰공고
# ──────────────────────────────────────────────

@dataclass
class BidAnnouncement:
    """
    입찰공고 모델

    나라장터 입찰공고정보서비스 API에서 수집한 공고 데이터를 담습니다.
    """
    bid_ntce_no: str                         # 입찰공고번호 (PK)
    bid_ntce_ord: Optional[str] = None       # 공고차수
    title: str = ""                          # 공고명
    org_name: Optional[str] = None           # 발주기관명
    demand_org_name: Optional[str] = None    # 수요기관명
    budget: Optional[int] = None             # 추정가격
    bid_begin_dt: Optional[str] = None       # 입찰개시일시
    bid_close_dt: Optional[str] = None       # 입찰마감일시
    category: Optional[str] = None           # 업종분류
    bid_method: Optional[str] = None         # 입찰방식
    contract_method: Optional[str] = None    # 계약방법
    region: Optional[str] = None             # 지역제한
    license_limit: Optional[str] = None      # 면허제한
    rfp_url: Optional[str] = None            # 첨부파일 URL
    rfp_text: Optional[str] = None           # 파싱된 RFP 텍스트
    collected_at: Optional[datetime] = None  # 수집일시

    @classmethod
    def from_dict(cls, data: dict) -> "BidAnnouncement":
        """딕셔너리에서 BidAnnouncement 객체를 생성합니다."""
        return cls(
            bid_ntce_no=data.get("bid_ntce_no", data.get("bidNtceNo", "")),
            bid_ntce_ord=data.get("bid_ntce_ord", data.get("bidNtceOrd")),
            title=data.get("title", data.get("bidNtceNm", "")),
            org_name=data.get("org_name", data.get("ntceInsttNm")),
            demand_org_name=data.get("demand_org_name", data.get("dminsttNm")),
            budget=data.get("budget", data.get("presmptPrce")),
            bid_begin_dt=data.get("bid_begin_dt", data.get("bidBeginDt")),
            bid_close_dt=data.get("bid_close_dt", data.get("bidClseDt")),
            category=data.get("category", data.get("industryCdNm")),
            bid_method=data.get("bid_method", data.get("bidMethdNm")),
            contract_method=data.get("contract_method", data.get("cntrctMthdNm")),
            region=data.get("region", data.get("rgstTyNm")),
            license_limit=data.get("license_limit", data.get("lmtGrpNm")),
            rfp_url=data.get("rfp_url"),
            rfp_text=data.get("rfp_text"),
            collected_at=_parse_timestamp(data.get("collected_at")),
        )

    def to_dict(self) -> dict:
        """객체를 딕셔너리로 변환합니다."""
        return {
            "bid_ntce_no": self.bid_ntce_no,
            "bid_ntce_ord": self.bid_ntce_ord,
            "title": self.title,
            "org_name": self.org_name,
            "demand_org_name": self.demand_org_name,
            "budget": self.budget,
            "bid_begin_dt": self.bid_begin_dt,
            "bid_close_dt": self.bid_close_dt,
            "category": self.category,
            "bid_method": self.bid_method,
            "contract_method": self.contract_method,
            "region": self.region,
            "license_limit": self.license_limit,
            "rfp_url": self.rfp_url,
            "rfp_text": self.rfp_text,
            "collected_at": _format_timestamp(self.collected_at),
        }


# ──────────────────────────────────────────────
# 낙찰정보
# ──────────────────────────────────────────────

@dataclass
class AwardInfo:
    """
    낙찰정보 모델

    과거 낙찰 이력 데이터를 담습니다. 경쟁사 분석 및 투찰률 예측에 활용됩니다.
    """
    id: Optional[int] = None                 # 자동 증가 PK
    bid_ntce_no: Optional[str] = None        # 입찰공고번호
    bid_title: Optional[str] = None          # 공고명
    winner_name: Optional[str] = None        # 낙찰업체명
    award_amount: Optional[int] = None       # 낙찰금액
    bid_rate: Optional[float] = None         # 투찰률
    award_date: Optional[str] = None         # 낙찰일
    budget: Optional[int] = None             # 예정가격
    collected_at: Optional[datetime] = None  # 수집일시

    @classmethod
    def from_dict(cls, data: dict) -> "AwardInfo":
        """딕셔너리에서 AwardInfo 객체를 생성합니다."""
        # 투찰률을 float로 안전하게 변환
        bid_rate = data.get("bid_rate", data.get("bidprcRate"))
        if bid_rate is not None:
            try:
                bid_rate = float(bid_rate)
            except (ValueError, TypeError):
                bid_rate = None

        # 금액 필드를 int로 안전하게 변환
        award_amount = data.get("award_amount", data.get("sucsfbidAmt"))
        if award_amount is not None:
            try:
                award_amount = int(award_amount)
            except (ValueError, TypeError):
                award_amount = None

        budget = data.get("budget", data.get("presmptPrce"))
        if budget is not None:
            try:
                budget = int(budget)
            except (ValueError, TypeError):
                budget = None

        return cls(
            id=data.get("id"),
            bid_ntce_no=data.get("bid_ntce_no", data.get("bidNtceNo")),
            bid_title=data.get("bid_title", data.get("bidNtceNm")),
            winner_name=data.get("winner_name", data.get("opengRsltCmpnmNm")),
            award_amount=award_amount,
            bid_rate=bid_rate,
            award_date=data.get("award_date", data.get("opengDt")),
            budget=budget,
            collected_at=_parse_timestamp(data.get("collected_at")),
        )

    def to_dict(self) -> dict:
        """객체를 딕셔너리로 변환합니다."""
        return {
            "id": self.id,
            "bid_ntce_no": self.bid_ntce_no,
            "bid_title": self.bid_title,
            "winner_name": self.winner_name,
            "award_amount": self.award_amount,
            "bid_rate": self.bid_rate,
            "award_date": self.award_date,
            "budget": self.budget,
            "collected_at": _format_timestamp(self.collected_at),
        }


# ──────────────────────────────────────────────
# 뉴스기사
# ──────────────────────────────────────────────

@dataclass
class NewsArticle:
    """
    뉴스기사 모델

    네이버 뉴스 검색 API에서 수집한 기사 데이터를 담습니다.
    발주기관 동향 파악 및 공고 관련 뉴스 분석에 활용됩니다.
    """
    id: Optional[int] = None                 # 자동 증가 PK
    title: Optional[str] = None              # 기사 제목
    description: Optional[str] = None        # 기사 요약
    link: Optional[str] = None               # 기사 URL
    pub_date: Optional[str] = None           # 발행일
    search_query: Optional[str] = None       # 검색어
    related_bid_no: Optional[str] = None     # 관련 공고번호
    collected_at: Optional[datetime] = None  # 수집일시

    @classmethod
    def from_dict(cls, data: dict) -> "NewsArticle":
        """딕셔너리에서 NewsArticle 객체를 생성합니다."""
        return cls(
            id=data.get("id"),
            title=data.get("title"),
            description=data.get("description"),
            link=data.get("link"),
            pub_date=data.get("pub_date", data.get("pubDate")),
            search_query=data.get("search_query"),
            related_bid_no=data.get("related_bid_no"),
            collected_at=_parse_timestamp(data.get("collected_at")),
        )

    def to_dict(self) -> dict:
        """객체를 딕셔너리로 변환합니다."""
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "link": self.link,
            "pub_date": self.pub_date,
            "search_query": self.search_query,
            "related_bid_no": self.related_bid_no,
            "collected_at": _format_timestamp(self.collected_at),
        }


# ──────────────────────────────────────────────
# 분석결과
# ──────────────────────────────────────────────

@dataclass
class AnalysisResult:
    """
    분석결과 모델

    AI 분석을 통해 산출된 매칭 점수, 요약, 전략 보고서 등을 담습니다.
    """
    id: Optional[int] = None                 # 자동 증가 PK
    bid_ntce_no: Optional[str] = None        # 입찰공고번호
    biz_id: Optional[str] = None             # 매칭된 사업자
    relevance_score: Optional[float] = None  # 관련도 점수 (0~100)
    match_score: Optional[float] = None      # 사업자 매칭 점수 (0~100)
    summary: Optional[str] = None            # AI 요약
    strategy_report: Optional[str] = None    # 전략 보고서
    competitors: list = field(default_factory=list)  # 경쟁사 정보 (JSON)
    analyzed_at: Optional[datetime] = None   # 분석일시

    @classmethod
    def from_dict(cls, data: dict) -> "AnalysisResult":
        """딕셔너리에서 AnalysisResult 객체를 생성합니다."""
        # 점수 필드를 float로 안전하게 변환
        relevance = data.get("relevance_score")
        if relevance is not None:
            try:
                relevance = float(relevance)
            except (ValueError, TypeError):
                relevance = None

        match = data.get("match_score")
        if match is not None:
            try:
                match = float(match)
            except (ValueError, TypeError):
                match = None

        return cls(
            id=data.get("id"),
            bid_ntce_no=data.get("bid_ntce_no"),
            biz_id=data.get("biz_id"),
            relevance_score=relevance,
            match_score=match,
            summary=data.get("summary"),
            strategy_report=data.get("strategy_report"),
            competitors=_parse_json_field(data.get("competitors")),
            analyzed_at=_parse_timestamp(data.get("analyzed_at")),
        )

    def to_dict(self) -> dict:
        """객체를 딕셔너리로 변환합니다."""
        return {
            "id": self.id,
            "bid_ntce_no": self.bid_ntce_no,
            "biz_id": self.biz_id,
            "relevance_score": self.relevance_score,
            "match_score": self.match_score,
            "summary": self.summary,
            "strategy_report": self.strategy_report,
            "competitors": _dump_json_field(self.competitors),
            "analyzed_at": _format_timestamp(self.analyzed_at),
        }


# ──────────────────────────────────────────────
# DDL (테이블 생성 SQL)
# ──────────────────────────────────────────────

CREATE_TABLES_SQL = """
-- 사업자 프로필 테이블
CREATE TABLE IF NOT EXISTS business_profiles (
    biz_id          TEXT PRIMARY KEY,
    company_name    TEXT NOT NULL,
    ceo_name        TEXT,
    business_types  TEXT,           -- JSON 배열
    licenses        TEXT,           -- JSON 배열
    regions         TEXT,           -- JSON 배열
    past_projects   TEXT,           -- JSON 배열
    annual_revenue  INTEGER,
    employee_count  INTEGER,
    keywords        TEXT,           -- JSON 배열
    min_budget      INTEGER,
    max_budget      INTEGER,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 입찰공고 테이블
CREATE TABLE IF NOT EXISTS bid_announcements (
    bid_ntce_no     TEXT PRIMARY KEY,
    bid_ntce_ord    TEXT,
    title           TEXT NOT NULL,
    org_name        TEXT,
    demand_org_name TEXT,
    budget          INTEGER,
    bid_begin_dt    TEXT,
    bid_close_dt    TEXT,
    category        TEXT,
    bid_method      TEXT,
    contract_method TEXT,
    region          TEXT,
    license_limit   TEXT,
    rfp_url         TEXT,
    rfp_text        TEXT,
    collected_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 낙찰정보 테이블
CREATE TABLE IF NOT EXISTS award_infos (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    bid_ntce_no     TEXT,
    bid_title       TEXT,
    winner_name     TEXT,
    award_amount    INTEGER,
    bid_rate        REAL,
    award_date      TEXT,
    budget          INTEGER,
    collected_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(bid_ntce_no, winner_name)
);

-- 뉴스기사 테이블
CREATE TABLE IF NOT EXISTS news_articles (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    title           TEXT,
    description     TEXT,
    link            TEXT UNIQUE,
    pub_date        TEXT,
    search_query    TEXT,
    related_bid_no  TEXT,
    collected_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 분석결과 테이블
CREATE TABLE IF NOT EXISTS analysis_results (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    bid_ntce_no     TEXT,
    biz_id          TEXT,
    relevance_score REAL,
    match_score     REAL,
    summary         TEXT,
    strategy_report TEXT,
    competitors     TEXT,           -- JSON
    analyzed_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(bid_ntce_no, biz_id)
);

-- 인덱스: 자주 조회되는 컬럼에 대한 인덱스
CREATE INDEX IF NOT EXISTS idx_bid_collected_at ON bid_announcements(collected_at);
CREATE INDEX IF NOT EXISTS idx_bid_org_name ON bid_announcements(org_name);
CREATE INDEX IF NOT EXISTS idx_award_bid_no ON award_infos(bid_ntce_no);
CREATE INDEX IF NOT EXISTS idx_award_winner ON award_infos(winner_name);
CREATE INDEX IF NOT EXISTS idx_news_query ON news_articles(search_query);
CREATE INDEX IF NOT EXISTS idx_analysis_bid ON analysis_results(bid_ntce_no);
CREATE INDEX IF NOT EXISTS idx_analysis_biz ON analysis_results(biz_id);
"""
