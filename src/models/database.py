"""
SQLite 데이터베이스 관리 모듈

모든 데이터 테이블에 대한 CRUD 메서드를 제공하며,
context manager를 통해 안전한 연결 관리를 지원합니다.
"""

import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.config import DB_PATH
from src.models.schemas import (
    CREATE_TABLES_SQL,
    BusinessProfile,
    BidAnnouncement,
    AwardInfo,
    NewsArticle,
    AnalysisResult,
    _dump_json_field,
)

logger = logging.getLogger(__name__)


class DatabaseManager:
    """
    SQLite 데이터베이스 관리 클래스

    context manager(with문)를 지원하며, 각 테이블에 대한
    삽입·조회·수정·삭제·검색 메서드를 제공합니다.

    사용 예:
        with DatabaseManager() as db:
            db.save_bids(bid_list)
            bids = db.get_recent_bids(limit=10)
    """

    def __init__(self, db_path: Optional[Path] = None):
        """
        DatabaseManager 초기화

        Args:
            db_path: SQLite 데이터베이스 파일 경로.
                     None이면 config의 DB_PATH 사용.
        """
        self.db_path = db_path or DB_PATH
        self.conn: Optional[sqlite3.Connection] = None
        logger.debug("DatabaseManager 초기화: %s", self.db_path)

    def __enter__(self) -> "DatabaseManager":
        """context manager 진입 시 DB 연결을 생성합니다."""
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """context manager 종료 시 DB 연결을 닫습니다."""
        self.close()

    def connect(self) -> None:
        """데이터베이스에 연결합니다."""
        try:
            # 데이터 디렉터리가 없으면 생성
            self.db_path.parent.mkdir(parents=True, exist_ok=True)

            self.conn = sqlite3.connect(
                str(self.db_path), check_same_thread=False
            )
            # Row 객체로 결과를 받을 수 있도록 설정
            self.conn.row_factory = sqlite3.Row
            # WAL 모드 활성화 (동시 읽기 성능 향상)
            self.conn.execute("PRAGMA journal_mode=WAL")
            # 외래키 제약 활성화
            self.conn.execute("PRAGMA foreign_keys=ON")
            logger.debug("데이터베이스 연결 완료: %s", self.db_path)
        except sqlite3.Error as e:
            logger.error("데이터베이스 연결 실패: %s (오류: %s)", self.db_path, e)
            raise

    def close(self) -> None:
        """데이터베이스 연결을 닫습니다."""
        if self.conn:
            try:
                self.conn.close()
                logger.debug("데이터베이스 연결 종료")
            except sqlite3.Error as e:
                logger.warning("데이터베이스 연결 종료 중 오류: %s", e)
            finally:
                self.conn = None

    def _ensure_connection(self) -> sqlite3.Connection:
        """연결이 활성 상태인지 확인하고 반환합니다."""
        if self.conn is None:
            self.connect()
        return self.conn

    def get_connection(self) -> sqlite3.Connection:
        """내부 SQLite 연결 객체를 반환합니다."""
        return self._ensure_connection()

    # ──────────────────────────────────────────
    # 테이블 초기화
    # ──────────────────────────────────────────

    def init_db(self) -> None:
        """
        데이터베이스 테이블을 생성합니다.

        이미 존재하는 테이블은 건너뜁니다 (CREATE TABLE IF NOT EXISTS).
        """
        conn = self._ensure_connection()
        try:
            conn.executescript(CREATE_TABLES_SQL)
            conn.commit()
            logger.info("데이터베이스 테이블 초기화 완료")
        except sqlite3.Error as e:
            logger.error("테이블 초기화 실패: %s", e)
            raise

    # ──────────────────────────────────────────
    # 사업자 프로필 CRUD
    # ──────────────────────────────────────────

    def add_business(self, profile: BusinessProfile) -> None:
        """
        사업자 프로필을 추가합니다.

        동일한 biz_id가 존재하면 덮어씁니다 (UPSERT).

        Args:
            profile: BusinessProfile 객체
        """
        conn = self._ensure_connection()
        data = profile.to_dict()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        data["created_at"] = data.get("created_at") or now
        data["updated_at"] = now

        try:
            conn.execute(
                """
                INSERT INTO business_profiles
                    (biz_id, company_name, ceo_name, business_types, licenses,
                     regions, past_projects, annual_revenue, employee_count,
                     keywords, min_budget, max_budget, created_at, updated_at)
                VALUES
                    (:biz_id, :company_name, :ceo_name, :business_types, :licenses,
                     :regions, :past_projects, :annual_revenue, :employee_count,
                     :keywords, :min_budget, :max_budget, :created_at, :updated_at)
                ON CONFLICT(biz_id) DO UPDATE SET
                    company_name = excluded.company_name,
                    ceo_name = excluded.ceo_name,
                    business_types = excluded.business_types,
                    licenses = excluded.licenses,
                    regions = excluded.regions,
                    past_projects = excluded.past_projects,
                    annual_revenue = excluded.annual_revenue,
                    employee_count = excluded.employee_count,
                    keywords = excluded.keywords,
                    min_budget = excluded.min_budget,
                    max_budget = excluded.max_budget,
                    updated_at = excluded.updated_at
                """,
                data,
            )
            conn.commit()
            logger.info("사업자 프로필 저장 완료: %s (%s)", profile.company_name, profile.biz_id)
        except sqlite3.Error as e:
            conn.rollback()
            logger.error("사업자 프로필 저장 실패: %s (오류: %s)", profile.biz_id, e)
            raise

    def get_business(self, biz_id: str) -> Optional[BusinessProfile]:
        """
        사업자등록번호로 프로필을 조회합니다.

        Args:
            biz_id: 사업자등록번호

        Returns:
            BusinessProfile 객체 또는 None
        """
        conn = self._ensure_connection()
        try:
            cursor = conn.execute(
                "SELECT * FROM business_profiles WHERE biz_id = ?", (biz_id,)
            )
            row = cursor.fetchone()
            if row:
                return BusinessProfile.from_dict(dict(row))
            return None
        except sqlite3.Error as e:
            logger.error("사업자 프로필 조회 실패: %s (오류: %s)", biz_id, e)
            return None

    def get_businesses(self) -> list[BusinessProfile]:
        """
        전체 사업자 프로필 목록을 조회합니다.

        Returns:
            BusinessProfile 리스트
        """
        conn = self._ensure_connection()
        try:
            cursor = conn.execute(
                "SELECT * FROM business_profiles ORDER BY updated_at DESC"
            )
            return [BusinessProfile.from_dict(dict(row)) for row in cursor.fetchall()]
        except sqlite3.Error as e:
            logger.error("사업자 프로필 목록 조회 실패: %s", e)
            return []

    def update_business(self, profile: BusinessProfile) -> bool:
        """
        기존 사업자 프로필을 수정합니다.

        Args:
            profile: 수정된 BusinessProfile 객체

        Returns:
            수정 성공 여부
        """
        conn = self._ensure_connection()
        data = profile.to_dict()
        data["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        try:
            cursor = conn.execute(
                """
                UPDATE business_profiles SET
                    company_name = :company_name,
                    ceo_name = :ceo_name,
                    business_types = :business_types,
                    licenses = :licenses,
                    regions = :regions,
                    past_projects = :past_projects,
                    annual_revenue = :annual_revenue,
                    employee_count = :employee_count,
                    keywords = :keywords,
                    min_budget = :min_budget,
                    max_budget = :max_budget,
                    updated_at = :updated_at
                WHERE biz_id = :biz_id
                """,
                data,
            )
            conn.commit()
            if cursor.rowcount > 0:
                logger.info("사업자 프로필 수정 완료: %s", profile.biz_id)
                return True
            else:
                logger.warning("수정할 사업자 프로필을 찾을 수 없습니다: %s", profile.biz_id)
                return False
        except sqlite3.Error as e:
            conn.rollback()
            logger.error("사업자 프로필 수정 실패: %s (오류: %s)", profile.biz_id, e)
            return False

    def delete_business(self, biz_id: str) -> bool:
        """
        사업자 프로필을 삭제합니다.

        Args:
            biz_id: 사업자등록번호

        Returns:
            삭제 성공 여부
        """
        conn = self._ensure_connection()
        try:
            cursor = conn.execute(
                "DELETE FROM business_profiles WHERE biz_id = ?", (biz_id,)
            )
            conn.commit()
            if cursor.rowcount > 0:
                logger.info("사업자 프로필 삭제 완료: %s", biz_id)
                return True
            else:
                logger.warning("삭제할 사업자 프로필을 찾을 수 없습니다: %s", biz_id)
                return False
        except sqlite3.Error as e:
            conn.rollback()
            logger.error("사업자 프로필 삭제 실패: %s (오류: %s)", biz_id, e)
            return False

    # ──────────────────────────────────────────
    # 입찰공고 CRUD
    # ──────────────────────────────────────────

    def save_bids(self, bids: list[BidAnnouncement]) -> int:
        """
        입찰공고 목록을 일괄 저장합니다.

        이미 존재하는 공고번호는 무시합니다 (INSERT OR IGNORE).

        Args:
            bids: BidAnnouncement 리스트

        Returns:
            새로 저장된 건수
        """
        conn = self._ensure_connection()
        saved_count = 0

        try:
            for bid in bids:
                data = bid.to_dict()
                data["collected_at"] = data.get("collected_at") or datetime.now().strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
                cursor = conn.execute(
                    """
                    INSERT OR IGNORE INTO bid_announcements
                        (bid_ntce_no, bid_ntce_ord, title, org_name, demand_org_name,
                         budget, bid_begin_dt, bid_close_dt, category, bid_method,
                         contract_method, region, license_limit, rfp_url, rfp_text,
                         collected_at)
                    VALUES
                        (:bid_ntce_no, :bid_ntce_ord, :title, :org_name, :demand_org_name,
                         :budget, :bid_begin_dt, :bid_close_dt, :category, :bid_method,
                         :contract_method, :region, :license_limit, :rfp_url, :rfp_text,
                         :collected_at)
                    """,
                    data,
                )
                if cursor.rowcount > 0:
                    saved_count += 1

            conn.commit()
            logger.info("입찰공고 저장 완료: %d건 (전체 %d건 중)", saved_count, len(bids))
            return saved_count

        except sqlite3.Error as e:
            conn.rollback()
            logger.error("입찰공고 저장 실패: %s", e)
            raise

    def get_bid_by_no(self, bid_ntce_no: str) -> Optional[BidAnnouncement]:
        """
        공고번호로 입찰공고를 조회합니다.

        Args:
            bid_ntce_no: 입찰공고번호

        Returns:
            BidAnnouncement 객체 또는 None
        """
        conn = self._ensure_connection()
        try:
            cursor = conn.execute(
                "SELECT * FROM bid_announcements WHERE bid_ntce_no = ?",
                (bid_ntce_no,),
            )
            row = cursor.fetchone()
            if row:
                return BidAnnouncement.from_dict(dict(row))
            return None
        except sqlite3.Error as e:
            logger.error("입찰공고 조회 실패: %s (오류: %s)", bid_ntce_no, e)
            return None

    def get_recent_bids(self, limit: int = 50) -> list[BidAnnouncement]:
        """
        최근 수집된 입찰공고 목록을 조회합니다.

        Args:
            limit: 최대 반환 건수 (기본 50)

        Returns:
            BidAnnouncement 리스트
        """
        conn = self._ensure_connection()
        try:
            cursor = conn.execute(
                """
                SELECT * FROM bid_announcements
                ORDER BY collected_at DESC
                LIMIT ?
                """,
                (limit,),
            )
            return [BidAnnouncement.from_dict(dict(row)) for row in cursor.fetchall()]
        except sqlite3.Error as e:
            logger.error("최근 공고 조회 실패: %s", e)
            return []

    def search_bids(
        self,
        keyword: Optional[str] = None,
        org_name: Optional[str] = None,
        min_budget: Optional[int] = None,
        max_budget: Optional[int] = None,
        limit: int = 100,
    ) -> list[BidAnnouncement]:
        """
        조건에 맞는 입찰공고를 검색합니다.

        Args:
            keyword: 공고명에 포함된 키워드 (LIKE 검색)
            org_name: 발주기관명 (부분 일치)
            min_budget: 최소 추정가격
            max_budget: 최대 추정가격
            limit: 최대 반환 건수

        Returns:
            BidAnnouncement 리스트
        """
        conn = self._ensure_connection()
        conditions = []
        params = []

        if keyword:
            conditions.append("title LIKE ?")
            params.append(f"%{keyword}%")
        if org_name:
            conditions.append("org_name LIKE ?")
            params.append(f"%{org_name}%")
        if min_budget is not None:
            conditions.append("budget >= ?")
            params.append(min_budget)
        if max_budget is not None:
            conditions.append("budget <= ?")
            params.append(max_budget)

        where_clause = " AND ".join(conditions) if conditions else "1=1"
        params.append(limit)

        try:
            cursor = conn.execute(
                f"""
                SELECT * FROM bid_announcements
                WHERE {where_clause}
                ORDER BY collected_at DESC
                LIMIT ?
                """,
                params,
            )
            return [BidAnnouncement.from_dict(dict(row)) for row in cursor.fetchall()]
        except sqlite3.Error as e:
            logger.error("입찰공고 검색 실패: %s", e)
            return []

    # ──────────────────────────────────────────
    # 낙찰정보 CRUD
    # ──────────────────────────────────────────

    def save_awards(self, awards: list[AwardInfo]) -> int:
        """
        낙찰정보 목록을 일괄 저장합니다.

        동일 공고번호+낙찰업체명 조합이 이미 존재하면 무시합니다.

        Args:
            awards: AwardInfo 리스트

        Returns:
            새로 저장된 건수
        """
        conn = self._ensure_connection()
        saved_count = 0

        try:
            for award in awards:
                data = award.to_dict()
                data["collected_at"] = data.get("collected_at") or datetime.now().strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
                # id 필드는 AUTOINCREMENT이므로 제외
                cursor = conn.execute(
                    """
                    INSERT OR IGNORE INTO award_infos
                        (bid_ntce_no, bid_title, winner_name, award_amount,
                         bid_rate, award_date, budget, collected_at)
                    VALUES
                        (:bid_ntce_no, :bid_title, :winner_name, :award_amount,
                         :bid_rate, :award_date, :budget, :collected_at)
                    """,
                    data,
                )
                if cursor.rowcount > 0:
                    saved_count += 1

            conn.commit()
            logger.info("낙찰정보 저장 완료: %d건 (전체 %d건 중)", saved_count, len(awards))
            return saved_count

        except sqlite3.Error as e:
            conn.rollback()
            logger.error("낙찰정보 저장 실패: %s", e)
            raise

    def get_awards_by_bid_no(self, bid_ntce_no: str) -> list[AwardInfo]:
        """
        공고번호로 낙찰정보를 조회합니다.

        Args:
            bid_ntce_no: 입찰공고번호

        Returns:
            AwardInfo 리스트
        """
        conn = self._ensure_connection()
        try:
            cursor = conn.execute(
                "SELECT * FROM award_infos WHERE bid_ntce_no = ?",
                (bid_ntce_no,),
            )
            return [AwardInfo.from_dict(dict(row)) for row in cursor.fetchall()]
        except sqlite3.Error as e:
            logger.error("낙찰정보 조회 실패 (공고번호: %s): %s", bid_ntce_no, e)
            return []

    def get_awards_by_title(self, keyword: str, limit: int = 100) -> list[AwardInfo]:
        """
        공고명 키워드로 낙찰정보를 검색합니다.

        Args:
            keyword: 공고명에 포함된 키워드 (LIKE 검색)
            limit: 최대 반환 건수

        Returns:
            AwardInfo 리스트
        """
        conn = self._ensure_connection()
        try:
            cursor = conn.execute(
                """
                SELECT * FROM award_infos
                WHERE bid_title LIKE ?
                ORDER BY award_date DESC
                LIMIT ?
                """,
                (f"%{keyword}%", limit),
            )
            return [AwardInfo.from_dict(dict(row)) for row in cursor.fetchall()]
        except sqlite3.Error as e:
            logger.error("낙찰정보 검색 실패 (키워드: %s): %s", keyword, e)
            return []

    # ──────────────────────────────────────────
    # 뉴스기사 CRUD
    # ──────────────────────────────────────────

    def save_news(self, articles: list[NewsArticle]) -> int:
        """
        뉴스기사 목록을 일괄 저장합니다.

        동일 링크의 기사가 이미 존재하면 무시합니다.

        Args:
            articles: NewsArticle 리스트

        Returns:
            새로 저장된 건수
        """
        conn = self._ensure_connection()
        saved_count = 0

        try:
            for article in articles:
                data = article.to_dict()
                data["collected_at"] = data.get("collected_at") or datetime.now().strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
                cursor = conn.execute(
                    """
                    INSERT OR IGNORE INTO news_articles
                        (title, description, link, pub_date, search_query,
                         related_bid_no, collected_at)
                    VALUES
                        (:title, :description, :link, :pub_date, :search_query,
                         :related_bid_no, :collected_at)
                    """,
                    data,
                )
                if cursor.rowcount > 0:
                    saved_count += 1

            conn.commit()
            logger.info("뉴스기사 저장 완료: %d건 (전체 %d건 중)", saved_count, len(articles))
            return saved_count

        except sqlite3.Error as e:
            conn.rollback()
            logger.error("뉴스기사 저장 실패: %s", e)
            raise

    def get_news_by_query(self, query: str, limit: int = 50) -> list[NewsArticle]:
        """
        검색어로 뉴스기사를 조회합니다.

        Args:
            query: 검색어 (정확 일치)
            limit: 최대 반환 건수

        Returns:
            NewsArticle 리스트
        """
        conn = self._ensure_connection()
        try:
            cursor = conn.execute(
                """
                SELECT * FROM news_articles
                WHERE search_query = ?
                ORDER BY collected_at DESC
                LIMIT ?
                """,
                (query, limit),
            )
            return [NewsArticle.from_dict(dict(row)) for row in cursor.fetchall()]
        except sqlite3.Error as e:
            logger.error("뉴스기사 조회 실패 (검색어: %s): %s", query, e)
            return []

    # ──────────────────────────────────────────
    # 분석결과 CRUD
    # ──────────────────────────────────────────

    def save_analysis(self, result: AnalysisResult) -> int:
        """
        분석결과를 저장합니다. 같은 공고번호가 있으면 최신 결과로 업데이트합니다.

        Args:
            result: AnalysisResult 객체

        Returns:
            저장된 레코드의 ID
        """
        conn = self._ensure_connection()
        data = result.to_dict()
        data["analyzed_at"] = data.get("analyzed_at") or datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        )

        try:
            # ON CONFLICT UPSERT — DELETE+INSERT 대신 원자적 업데이트로 데이터 유실 방지
            cursor = conn.execute(
                """
                INSERT INTO analysis_results
                    (bid_ntce_no, biz_id, relevance_score, match_score,
                     summary, strategy_report, competitors, analyzed_at)
                VALUES
                    (:bid_ntce_no, :biz_id, :relevance_score, :match_score,
                     :summary, :strategy_report, :competitors, :analyzed_at)
                ON CONFLICT(bid_ntce_no, biz_id) DO UPDATE SET
                    relevance_score = excluded.relevance_score,
                    match_score = excluded.match_score,
                    summary = excluded.summary,
                    strategy_report = excluded.strategy_report,
                    competitors = excluded.competitors,
                    analyzed_at = excluded.analyzed_at
                """,
                data,
            )
            conn.commit()
            # lastrowid는 UPDATE 시 0을 반환하므로 실제 ID를 조회
            record_id = cursor.lastrowid
            if not record_id:
                row = conn.execute(
                    "SELECT id FROM analysis_results WHERE bid_ntce_no = ? AND biz_id = ?",
                    (result.bid_ntce_no, result.biz_id),
                ).fetchone()
                record_id = row[0] if row else 0
            logger.info(
                "분석결과 저장 완료: ID=%d (공고: %s, 사업자: %s)",
                record_id, result.bid_ntce_no, result.biz_id,
            )
            return record_id

        except sqlite3.Error as e:
            conn.rollback()
            logger.error("분석결과 저장 실패: %s", e)
            raise

    def delete_analysis(self, analysis_id: int) -> bool:
        """분석결과를 삭제합니다."""
        conn = self._ensure_connection()
        try:
            cursor = conn.execute(
                "DELETE FROM analysis_results WHERE id = ?", (analysis_id,)
            )
            conn.commit()
            deleted = cursor.rowcount > 0
            if deleted:
                logger.info("분석결과 삭제 완료: ID=%d", analysis_id)
            return deleted
        except sqlite3.Error as e:
            conn.rollback()
            logger.error("분석결과 삭제 실패: %s", e)
            raise

    def delete_all_analyses(self) -> int:
        """모든 분석결과를 삭제합니다."""
        conn = self._ensure_connection()
        try:
            cursor = conn.execute("DELETE FROM analysis_results")
            conn.commit()
            count = cursor.rowcount
            logger.info("분석결과 전체 삭제: %d건", count)
            return count
        except sqlite3.Error as e:
            conn.rollback()
            logger.error("분석결과 전체 삭제 실패: %s", e)
            raise

    def get_analyses_by_bid(self, bid_ntce_no: str) -> list[AnalysisResult]:
        """
        공고번호로 분석결과를 조회합니다.

        Args:
            bid_ntce_no: 입찰공고번호

        Returns:
            AnalysisResult 리스트
        """
        conn = self._ensure_connection()
        try:
            cursor = conn.execute(
                """
                SELECT * FROM analysis_results
                WHERE bid_ntce_no = ?
                ORDER BY analyzed_at DESC
                """,
                (bid_ntce_no,),
            )
            return [AnalysisResult.from_dict(dict(row)) for row in cursor.fetchall()]
        except sqlite3.Error as e:
            logger.error("분석결과 조회 실패 (공고: %s): %s", bid_ntce_no, e)
            return []

    def get_analyses_by_biz(self, biz_id: str) -> list[AnalysisResult]:
        """
        사업자 ID로 분석결과를 조회합니다.

        Args:
            biz_id: 사업자등록번호

        Returns:
            AnalysisResult 리스트
        """
        conn = self._ensure_connection()
        try:
            cursor = conn.execute(
                """
                SELECT * FROM analysis_results
                WHERE biz_id = ?
                ORDER BY analyzed_at DESC
                """,
                (biz_id,),
            )
            return [AnalysisResult.from_dict(dict(row)) for row in cursor.fetchall()]
        except sqlite3.Error as e:
            logger.error("분석결과 조회 실패 (사업자: %s): %s", biz_id, e)
            return []

    # ──────────────────────────────────────────
    # 유틸리티
    # ──────────────────────────────────────────

    def get_stats(self) -> dict:
        """
        데이터베이스 통계 정보를 반환합니다.

        Returns:
            각 테이블의 레코드 수를 담은 딕셔너리
        """
        conn = self._ensure_connection()
        stats = {}
        # 허용된 테이블 목록을 화이트리스트로 관리 (SQL Injection 방지)
        _ALLOWED_TABLES = {
            "business_profiles",
            "bid_announcements",
            "award_infos",
            "news_articles",
            "analysis_results",
        }

        for table in _ALLOWED_TABLES:
            try:
                # 테이블명은 화이트리스트에서만 가져오므로 파라미터화 불필요
                cursor = conn.execute(f"SELECT COUNT(*) FROM [{table}]")
                row = cursor.fetchone()
                stats[table] = row[0] if row else 0
            except sqlite3.Error:
                stats[table] = -1

        return stats
