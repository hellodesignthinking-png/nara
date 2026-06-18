"""
SQLite 데이터베이스 관리 모듈

모든 데이터 테이블에 대한 CRUD 메서드를 제공하며,
context manager를 통해 안전한 연결 관리를 지원합니다.
"""

import json
import logging
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.config import DB_PATH
import os
import psycopg2
import psycopg2.extras
from src.config import DB_PATH
from src.models.schemas import (
    CREATE_TABLES_SQL,
    CREATE_TABLES_PG_SQL,
    BusinessProfile,
    BidAnnouncement,
    AwardInfo,
    NewsArticle,
    AnalysisResult,
    _dump_json_field,
    _parse_json_field,
)

logger = logging.getLogger(__name__)


class PostgresConnectionProxy:
    """
    psycopg2 커넥션을 sqlite3.Connection 인터페이스처럼 동작하도록 래핑하는 프록시 클래스.
    """
    def __init__(self, conn):
        self._conn = conn

    def cursor(self):
        # sqlite3.Row와 호환되는 DictCursor 사용
        cur = self._conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        return PostgresCursorProxy(cur)

    def execute(self, sql, parameters=None):
        if sql.strip().upper() in ("BEGIN TRANSACTION", "BEGIN"):
            return PostgresCursorProxy(None)
        cur = self.cursor()
        cur.execute(sql, parameters)
        return cur

    def executemany(self, sql, seq_of_parameters):
        cur = self.cursor()
        cur.executemany(sql, seq_of_parameters)
        return cur

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            self._conn.rollback()
        else:
            self._conn.commit()
        return False


class PostgresCursorProxy:
    """
    psycopg2 커서 객체를 sqlite3.Cursor 인터페이스처럼 동작하도록 래핑하는 프록시 클래스.
    """
    def __init__(self, cursor):
        self._cursor = cursor

    def execute(self, sql, parameters=None):
        if self._cursor is None or sql.strip().upper() in ("BEGIN TRANSACTION", "BEGIN"):
            return self
        sql_translated = self._translate_query(sql)
        # PostgreSQL placeholders는 list, tuple, dict여야 함
        if parameters is None:
            self._cursor.execute(sql_translated)
        else:
            if isinstance(parameters, (list, tuple, dict)):
                self._cursor.execute(sql_translated, parameters)
            else:
                self._cursor.execute(sql_translated, (parameters,))
        return self

    def executemany(self, sql, seq_of_parameters):
        sql_translated = self._translate_query(sql)
        self._cursor.executemany(sql_translated, seq_of_parameters)
        return self

    def fetchone(self):
        return self._cursor.fetchone()

    def fetchall(self):
        return self._cursor.fetchall()

    @property
    def rowcount(self):
        return self._cursor.rowcount

    @property
    def lastrowid(self):
        return 0

    def close(self):
        self._cursor.close()

    def _translate_query(self, sql: str) -> str:
        import re
        # 1. Named parameters 변환 (:name → %(name)s) — executemany 호환
        sql_new = re.sub(r':([a-zA-Z_][a-zA-Z0-9_]*)', r'%(\1)s', sql)
        
        # 2. 위치 플레이스홀더 변환 (? → %s) — named 변환 후에 수행
        sql_new = sql_new.replace("?", "%s")
        
        # 3. INSERT OR IGNORE 변환
        if "INSERT OR IGNORE" in sql_new:
            sql_new = sql_new.replace("INSERT OR IGNORE", "INSERT")
            if "INTO user_favorites" in sql_new:
                sql_new += " ON CONFLICT (username, bid_ntce_no) DO NOTHING"
            elif "INTO business_members" in sql_new:
                sql_new += " ON CONFLICT (biz_id, username) DO NOTHING"
            elif "INTO award_infos" in sql_new:
                sql_new += " ON CONFLICT (bid_ntce_no, winner_name) DO NOTHING"
            elif "INTO analysis_results" in sql_new:
                sql_new += " ON CONFLICT (bid_ntce_no, biz_id) DO NOTHING"
            elif "INTO news_articles" in sql_new:
                sql_new += " ON CONFLICT (link) DO NOTHING"
            elif "INTO users" in sql_new:
                sql_new += " ON CONFLICT (username) DO NOTHING"
            elif "INTO business_profiles" in sql_new:
                sql_new += " ON CONFLICT (biz_id) DO NOTHING"
            elif "INTO bid_announcements" in sql_new:
                sql_new += " ON CONFLICT (bid_ntce_no) DO NOTHING"
            elif "INTO user_ai_settings" in sql_new:
                sql_new += " ON CONFLICT (username) DO NOTHING"
            elif "INTO municipal_policies" in sql_new:
                sql_new += " ON CONFLICT (region, title) DO NOTHING"
            else:
                sql_new += " ON CONFLICT DO NOTHING"

        # 4. INSERT OR REPLACE 변환
        elif "INSERT OR REPLACE" in sql_new:
            sql_new = sql_new.replace("INSERT OR REPLACE", "INSERT")
            if "INTO user_favorites" in sql_new:
                if "analysis_done" in sql_new:
                    sql_new += " ON CONFLICT (username, bid_ntce_no) DO UPDATE SET status = EXCLUDED.status, memo = EXCLUDED.memo, partners = EXCLUDED.partners, checklist = EXCLUDED.checklist, added_at = EXCLUDED.added_at, title = EXCLUDED.title, org_name = EXCLUDED.org_name, budget = EXCLUDED.budget, bid_close_dt = EXCLUDED.bid_close_dt, analysis_done = EXCLUDED.analysis_done, analysis_summary = EXCLUDED.analysis_summary"
                elif "title" in sql_new:
                    sql_new += " ON CONFLICT (username, bid_ntce_no) DO UPDATE SET status = EXCLUDED.status, memo = EXCLUDED.memo, partners = EXCLUDED.partners, checklist = EXCLUDED.checklist, added_at = EXCLUDED.added_at, title = EXCLUDED.title, org_name = EXCLUDED.org_name, budget = EXCLUDED.budget, bid_close_dt = EXCLUDED.bid_close_dt"
                else:
                    sql_new += " ON CONFLICT (username, bid_ntce_no) DO UPDATE SET status = EXCLUDED.status, memo = EXCLUDED.memo, partners = EXCLUDED.partners, checklist = EXCLUDED.checklist, added_at = EXCLUDED.added_at"
            elif "INTO user_ai_settings" in sql_new:
                sql_new += " ON CONFLICT (username) DO UPDATE SET bid_target = EXCLUDED.bid_target, relevance_weight = EXCLUDED.relevance_weight, capacity_weight = EXCLUDED.capacity_weight, credit_weight = EXCLUDED.credit_weight, ai_persona = EXCLUDED.ai_persona, custom_keywords = EXCLUDED.custom_keywords, updated_at = EXCLUDED.updated_at"
            elif "INTO users" in sql_new:
                sql_new += " ON CONFLICT (username) DO UPDATE SET password_hash = EXCLUDED.password_hash, email = EXCLUDED.email, is_admin = EXCLUDED.is_admin"
            elif "INTO business_profiles" in sql_new:
                sql_new += " ON CONFLICT (biz_id) DO UPDATE SET company_name = EXCLUDED.company_name, ceo_name = EXCLUDED.ceo_name, business_types = EXCLUDED.business_types, licenses = EXCLUDED.licenses, regions = EXCLUDED.regions, past_projects = EXCLUDED.past_projects, annual_revenue = EXCLUDED.annual_revenue, employee_count = EXCLUDED.employee_count, keywords = EXCLUDED.keywords, min_budget = EXCLUDED.min_budget, max_budget = EXCLUDED.max_budget, credit_rating = EXCLUDED.credit_rating, company_type = EXCLUDED.company_type, has_sanctions = EXCLUDED.has_sanctions, updated_at = EXCLUDED.updated_at"
            else:
                sql_new += " ON CONFLICT DO NOTHING"

        # 5. GROUP_CONCAT → string_agg + TEXT 캐스트
        if "GROUP_CONCAT(" in sql_new:
            sql_new = sql_new.replace("GROUP_CONCAT(", "string_agg(")
            # string_agg은 TEXT 타입 인자 필요
            sql_new = re.sub(r'string_agg\(([^,]+),', r'string_agg(\1::text,', sql_new)

        return sql_new


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
        """
        self.db_path = db_path or DB_PATH
        self.db_url = os.getenv("SUPABASE_DB_URL") or os.getenv("DATABASE_URL")
        self.is_postgres = bool(self.db_url)
        self.conn = None
        self._local = threading.local()
        if self.is_postgres:
            logger.info("PostgreSQL(Supabase) 모드 활성화")
        else:
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
        if self.is_postgres:
            try:
                import psycopg2
                import psycopg2.extras
                raw_conn = psycopg2.connect(self.db_url)
                raw_conn.autocommit = False
                self.conn = PostgresConnectionProxy(raw_conn)
                logger.info("PostgreSQL 데이터베이스 연결 완료")
                return
            except Exception as e:
                logger.error("PostgreSQL 데이터베이스 연결 실패: %s. SQLite Fallback 모드로 전환합니다.", e)
                self.is_postgres = False

        try:
            # 데이터 디렉터리가 없으면 생성
            self.db_path.parent.mkdir(parents=True, exist_ok=True)

            self.conn = sqlite3.connect(
                str(self.db_path), check_same_thread=False, timeout=30.0
            )
            # Row 객체로 결과를 받을 수 있도록 설정
            self.conn.row_factory = sqlite3.Row
            # WAL 모드 활성화 (동시 읽기 성능 향상)
            self.conn.execute("PRAGMA journal_mode=WAL")
            # 외래키 제약 활성화
            self.conn.execute("PRAGMA foreign_keys=ON")
            logger.debug("데이터베이스 연결 완료: %s", self.db_path)
        except Exception as e:
            logger.error("데이터베이스 연결 실패: %s (오류: %s)", self.db_path, e)
            raise

    def close(self) -> None:
        """데이터베이스 연결을 닫습니다."""
        if self.conn:
            try:
                self.conn.close()
                logger.debug("데이터베이스 연결 종료")
            except Exception as e:
                logger.warning("데이터베이스 연결 종료 중 오류: %s", e)
            finally:
                self.conn = None

    def _ensure_connection(self):
        """연결이 활성 상태인지 확인하고 반환합니다."""
        if self.conn is not None:
            try:
                # 연결이 살아있는지 ping 확인
                self.conn.execute("SELECT 1")
                return self.conn
            except Exception:
                logger.warning("데이터베이스 연결이 끊어져 있습니다. 재연결합니다.")
                self.conn = None
        self.connect()
        return self.conn

    def _get_thread_connection(self):
        """현재 쓰레드의 연결을 반환합니다. 쓰레드 안전한 연결 관리를 제공합니다."""
        conn = getattr(self._local, 'conn', None)
        if conn is not None:
            try:
                conn.execute("SELECT 1")
                return conn
            except Exception:
                self._local.conn = None

        if self.is_postgres:
            try:
                import psycopg2
                import psycopg2.extras
                raw_conn = psycopg2.connect(self.db_url)
                raw_conn.autocommit = True
                conn = PostgresConnectionProxy(raw_conn)
                self._local.conn = conn
                return conn
            except Exception as e:
                logger.error("PostgreSQL 쓰레드 커넥션 생성 실패: %s", e)
                raise

        # SQLite 새 연결 생성
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        self._local.conn = conn
        return conn

    def get_connection(self):
        """내부 연결 객체를 반환합니다."""
        return self._ensure_connection()

    # ──────────────────────────────────────────
    # 스키마 버전 관리 & 마이그레이션
    # ──────────────────────────────────────────

    # 마이그레이션 레지스트리: 버전 → (설명, SQL 목록)
    # 새 마이그레이션 추가 시 _MIGRATIONS에 항목을 추가하면 init_db()가 자동으로 적용합니다.
    _MIGRATIONS: dict[int, tuple[str, list[str]]] = {
        1: (
            "초기 스키마 생성",
            [CREATE_TABLES_SQL],
        ),
        2: (
            "business_profiles에 신용등급, 기업규모, 제재이력 필드 추가",
            [
                "ALTER TABLE business_profiles ADD COLUMN credit_rating TEXT DEFAULT 'BBB';",
                "ALTER TABLE business_profiles ADD COLUMN company_type TEXT;",
                "ALTER TABLE business_profiles ADD COLUMN has_sanctions INTEGER DEFAULT 0;"
            ],
        ),
        3: (
            "회원(users) 및 사용자 관심공고(user_favorites) 테이블 추가 및 다중 사용자 지원 마이그레이션",
            [
                "CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password_hash TEXT NOT NULL, email TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);",
                "ALTER TABLE business_profiles ADD COLUMN username TEXT REFERENCES users(username) DEFAULT 'admin';",
                "CREATE TABLE IF NOT EXISTS user_favorites (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL, bid_ntce_no TEXT NOT NULL, status TEXT DEFAULT 'reviewing', memo TEXT, partners TEXT, checklist TEXT, added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, UNIQUE(username, bid_ntce_no), FOREIGN KEY (username) REFERENCES users(username), FOREIGN KEY (bid_ntce_no) REFERENCES bid_announcements(bid_ntce_no));",
                "CREATE INDEX IF NOT EXISTS idx_fav_username ON user_favorites(username);",
                "CREATE INDEX IF NOT EXISTS idx_biz_username ON business_profiles(username);"
            ],
        ),
        4: (
            "사업자 테이블 단독 PK(biz_id) 변경 및 N:M 매핑용 멤버 테이블(business_members) 추가",
            [
                "CREATE TABLE IF NOT EXISTS business_profiles_new (biz_id TEXT PRIMARY KEY, company_name TEXT NOT NULL, ceo_name TEXT, business_types TEXT, licenses TEXT, regions TEXT, past_projects TEXT, annual_revenue INTEGER, employee_count INTEGER, keywords TEXT, min_budget INTEGER, max_budget INTEGER, credit_rating TEXT DEFAULT 'BBB', company_type TEXT, has_sanctions INTEGER DEFAULT 0, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);",
                "INSERT OR REPLACE INTO business_profiles_new (biz_id, company_name, ceo_name, business_types, licenses, regions, past_projects, annual_revenue, employee_count, keywords, min_budget, max_budget, credit_rating, company_type, has_sanctions, created_at, updated_at) SELECT biz_id, company_name, ceo_name, business_types, licenses, regions, past_projects, annual_revenue, employee_count, keywords, min_budget, max_budget, credit_rating, company_type, has_sanctions, created_at, updated_at FROM business_profiles GROUP BY biz_id;",
                "CREATE TABLE IF NOT EXISTS business_members (id INTEGER PRIMARY KEY AUTOINCREMENT, biz_id TEXT NOT NULL, username TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'member', joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, UNIQUE(biz_id, username), FOREIGN KEY (biz_id) REFERENCES business_profiles_new(biz_id) ON DELETE CASCADE, FOREIGN KEY (username) REFERENCES users(username) ON DELETE CASCADE);",
                "INSERT OR IGNORE INTO business_members (biz_id, username, role, joined_at) SELECT biz_id, username, 'owner', created_at FROM business_profiles;",
                "DROP INDEX IF EXISTS idx_biz_username;",
                "DROP TABLE business_profiles;",
                "ALTER TABLE business_profiles_new RENAME TO business_profiles;",
                "CREATE INDEX IF NOT EXISTS idx_biz_member_username ON business_members(username);",
                "CREATE INDEX IF NOT EXISTS idx_biz_member_biz ON business_members(biz_id);"
            ],
        ),
        5: (
            "users 테이블에 is_admin 컬럼 추가 및 user_ai_settings 테이블 신설",
            [
                "ALTER TABLE users ADD COLUMN is_admin INTEGER DEFAULT 0;",
                "CREATE TABLE IF NOT EXISTS user_ai_settings (username TEXT PRIMARY KEY, bid_target TEXT DEFAULT 'stable', relevance_weight REAL DEFAULT 0.35, capacity_weight REAL DEFAULT 0.35, credit_weight REAL DEFAULT 0.30, ai_persona TEXT DEFAULT 'strategic', custom_keywords TEXT, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY (username) REFERENCES users(username) ON DELETE CASCADE);",
                "UPDATE users SET is_admin = 1 WHERE username = 'admin';",
                "INSERT OR IGNORE INTO user_ai_settings (username) SELECT username FROM users;"
            ],
        ),
        6: (
            "같은 회사 소속 멤버들이 소통할 수 있는 사내 카페 게시판(company_cafe_posts) 테이블 추가",
            [
                """
                CREATE TABLE IF NOT EXISTS company_cafe_posts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    biz_id TEXT NOT NULL,
                    username TEXT NOT NULL,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (biz_id) REFERENCES business_profiles(biz_id) ON DELETE CASCADE,
                    FOREIGN KEY (username) REFERENCES users(username) ON DELETE CASCADE
                );
                """,
                "CREATE INDEX IF NOT EXISTS idx_cafe_biz_id ON company_cafe_posts(biz_id);"
            ],
        ),
        7: (
            "사내 카페 댓글(company_cafe_comments) 및 좋아요(company_cafe_likes) 테이블 추가",
            [
                """
                CREATE TABLE IF NOT EXISTS company_cafe_comments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    post_id INTEGER NOT NULL,
                    username TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (post_id) REFERENCES company_cafe_posts(id) ON DELETE CASCADE,
                    FOREIGN KEY (username) REFERENCES users(username) ON DELETE CASCADE
                );
                """,
                "CREATE INDEX IF NOT EXISTS idx_cafe_comment_post_id ON company_cafe_comments(post_id);",
                """
                CREATE TABLE IF NOT EXISTS company_cafe_likes (
                    post_id INTEGER NOT NULL,
                    username TEXT NOT NULL,
                    PRIMARY KEY (post_id, username),
                    FOREIGN KEY (post_id) REFERENCES company_cafe_posts(id) ON DELETE CASCADE,
                    FOREIGN KEY (username) REFERENCES users(username) ON DELETE CASCADE
                );
                """
            ],
        ),
        8: (
            "지자체 정책 및 뉴스 데이터(municipal_policies) 테이블 추가",
            [
                """
                CREATE TABLE IF NOT EXISTS municipal_policies (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    region TEXT NOT NULL,
                    title TEXT NOT NULL,
                    category TEXT,
                    department TEXT,
                    budget INTEGER,
                    content TEXT,
                    keywords TEXT,
                    ai_summary TEXT,
                    relevance_score REAL DEFAULT 0.0,
                    collected_at TEXT,
                    metadata TEXT,
                    UNIQUE(region, title)
                );
                """,
                "CREATE INDEX IF NOT EXISTS idx_policies_region ON municipal_policies(region);"
            ]
        ),
        9: (
            "user_favorites 테이블에 공고 메타데이터 캐시 컬럼 추가 (title, org_name, budget, bid_close_dt)",
            [
                "ALTER TABLE user_favorites ADD COLUMN title TEXT;",
                "ALTER TABLE user_favorites ADD COLUMN org_name TEXT;",
                "ALTER TABLE user_favorites ADD COLUMN budget INTEGER;",
                "ALTER TABLE user_favorites ADD COLUMN bid_close_dt TEXT;",
            ],
        ),
        10: (
            "user_favorites 테이블에 AI 분석 결과 캐시 컬럼 추가 (analysis_done, analysis_summary)",
            [
                "ALTER TABLE user_favorites ADD COLUMN analysis_done INTEGER DEFAULT 0;",
                "ALTER TABLE user_favorites ADD COLUMN analysis_summary TEXT;",
            ],
        ),
        11: (
            "business_profiles 테이블에 회사 정보 공유 여부(is_shared) 컬럼 추가",
            [
                "ALTER TABLE business_profiles ADD COLUMN is_shared INTEGER DEFAULT 0;",
            ],
        ),
        12: (
            "공동 수급 및 협업 제안 관리(collaboration_proposals) 테이블 신설",
            [
                """
                CREATE TABLE IF NOT EXISTS collaboration_proposals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sender_biz_id TEXT NOT NULL,
                    receiver_biz_id TEXT NOT NULL,
                    bid_ntce_no TEXT NOT NULL,
                    message TEXT,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (sender_biz_id) REFERENCES business_profiles(biz_id) ON DELETE CASCADE,
                    FOREIGN KEY (receiver_biz_id) REFERENCES business_profiles(biz_id) ON DELETE CASCADE,
                    FOREIGN KEY (bid_ntce_no) REFERENCES bid_announcements(bid_ntce_no) ON DELETE CASCADE
                );
                """,
            ],
        ),
        13: (
            "business_profiles 테이블에 홈페이지(website_url), 회사소개서(intro_file_url), 소셜네트워크(social_links) 컬럼 추가",
            [
                "ALTER TABLE business_profiles ADD COLUMN website_url TEXT;",
                "ALTER TABLE business_profiles ADD COLUMN intro_file_url TEXT;",
                "ALTER TABLE business_profiles ADD COLUMN social_links TEXT;",
            ],
        ),
    }

    CURRENT_SCHEMA_VERSION: int = 13

    def _get_schema_version(self, conn) -> int:
        """현재 DB의 스키마 버전을 조회합니다. 테이블이 없으면 0을 반환합니다."""
        if self.is_postgres:
            try:
                # pg에서 schema_version 테이블 존재 여부 확인
                cursor = conn.execute(
                    "SELECT EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'schema_version')"
                )
                row = cursor.fetchone()
                if not row or not row[0]:
                    return 0
                cursor = conn.execute("SELECT MAX(version) FROM schema_version")
                row = cursor.fetchone()
                return row[0] if row and row[0] is not None else 0
            except Exception:
                return 0

        try:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
            )
            if cursor.fetchone() is None:
                return 0
            cursor = conn.execute(
                "SELECT MAX(version) FROM schema_version"
            )
            row = cursor.fetchone()
            return row[0] if row and row[0] else 0
        except Exception:
            return 0

    def _set_schema_version(self, conn, version: int, description: str) -> None:
        """스키마 버전을 기록합니다."""
        if self.is_postgres:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_version (
                    version     INTEGER PRIMARY KEY,
                    description TEXT,
                    applied_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                "INSERT INTO schema_version (version, description) VALUES (%s, %s) ON CONFLICT (version) DO UPDATE SET description = EXCLUDED.description",
                (version, description),
            )
            return

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_version (
                version     INTEGER PRIMARY KEY,
                description TEXT,
                applied_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            "INSERT OR REPLACE INTO schema_version (version, description) VALUES (?, ?)",
            (version, description),
        )

    def init_db(self) -> None:
        """
        데이터베이스를 초기화하고 필요한 마이그레이션을 순차 적용합니다.
        """
        conn = self._ensure_connection()
        current_version = self._get_schema_version(conn)

        if current_version >= self.CURRENT_SCHEMA_VERSION:
            self._ensure_default_admin(conn)
            logger.debug(
                "데이터베이스 스키마 최신 상태 (v%d)", current_version
            )
            return

        if self.is_postgres:
            try:
                logger.info("PostgreSQL(Supabase) 스키마 DDL 실행 및 순차 마이그레이션 시작...")
                cursor = conn.cursor()
                cursor.execute(CREATE_TABLES_PG_SQL)
                conn.commit()

                # PostgreSQL 누락된 마이그레이션 적용
                for version in sorted(self._MIGRATIONS.keys()):
                    if version <= current_version:
                        continue

                    description, sql_list = self._MIGRATIONS[version]
                    logger.info("PostgreSQL 마이그레이션 v%d 적용 중: %s", version, description)

                    for sql in sql_list:
                        # SQLite 전용 구문(AUTOINCREMENT 등)이 있으면 PostgreSQL용으로 치환
                        pg_sql = sql.replace("AUTOINCREMENT", "").replace("INTEGER PRIMARY KEY", "SERIAL PRIMARY KEY")
                        try:
                            cursor.execute(pg_sql)
                        except Exception as e:
                            err_msg = str(e).lower()
                            if "already exists" in err_msg or "duplicate" in err_msg or "already has" in err_msg:
                                logger.warning("PostgreSQL 마이그레이션 경고 무시 (v%d): %s", version, err_msg)
                            else:
                                raise

                    self._set_schema_version(conn, version, description)
                    conn.commit()

                self._set_schema_version(conn, self.CURRENT_SCHEMA_VERSION, "PostgreSQL 스키마 초기화 및 마이그레이션 완료")
                conn.commit()
                logger.info("PostgreSQL(Supabase) 스키마 초기화 완료")
            except Exception as e:
                conn.rollback()
                logger.error("PostgreSQL 스키마 DDL 실행 실패: %s", e)
                raise
            self._ensure_default_admin(conn)
            return

        # 누락된 모든 버전을 순차적으로 적용합니다. (최초 생성 시 current_version == 0)
        try:
            for version in sorted(self._MIGRATIONS.keys()):
                if version <= current_version:
                    continue

                description, sql_list = self._MIGRATIONS[version]
                logger.info(
                    "마이그레이션 v%d 적용 중: %s", version, description
                )

                for sql in sql_list:
                    try:
                        conn.executescript(sql)
                    except sqlite3.OperationalError as e:
                        err_msg = str(e)
                        if "duplicate column name" in err_msg or "already exists" in err_msg or "duplicate key" in err_msg:
                            logger.warning(
                                "마이그레이션 SQL 실행 중 무시 가능한 오류 발생 (버전 %d): %s", version, err_msg
                            )
                        else:
                            raise

                self._set_schema_version(conn, version, description)
                conn.commit()
                logger.info("마이그레이션 v%d 적용 완료", version)

            logger.info(
                "데이터베이스 스키마 업데이트 완료 (v%d → v%d)",
                current_version, self.CURRENT_SCHEMA_VERSION,
            )
        except Exception as e:
            conn.rollback()
            logger.error("마이그레이션 실패 (v%d): %s", version, e)
            raise

        # 하위 호환성을 위해 디폴트 'admin' 사용자 무결성을 보장합니다.
        self._ensure_default_admin(conn)

    def _ensure_default_admin(self, conn: sqlite3.Connection) -> None:
        """
        하위 호환성과 기존 외래키 제약조건 위반을 방지하기 위해
        디폴트 'admin' 사용자가 users 테이블에 반드시 존재하도록 보장합니다.
        또한 admin에게 관리자 권한(is_admin=1)과 디폴트 AI 설정을 부여합니다.
        
        admin 비밀번호가 'default_placeholder'인 경우 올바른 PBKDF2 해시로 자동 변환합니다.
        기본 비밀번호: admin1234
        """
        import hashlib
        import secrets

        def _hash(password: str) -> str:
            salt = "nara_default_admin_salt_v1"
            h = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100000)
            return f"pbkdf2_sha256$100000${salt}${h.hex()}"

        default_hash = _hash("admin1234")

        try:
            conn.execute(
                "INSERT OR IGNORE INTO users (username, password_hash, email, is_admin) VALUES ('admin', ?, 'admin@nara-analyzer.local', 1)",
                (default_hash,)
            )
            # 기존 admin의 비밀번호가 placeholder이면 올바른 해시로 업데이트
            conn.execute(
                "UPDATE users SET password_hash = ? WHERE username = 'admin' AND password_hash = 'default_placeholder'",
                (default_hash,)
            )
            conn.execute(
                "UPDATE users SET is_admin = 1 WHERE username = 'admin'"
            )
            conn.execute(
                "INSERT OR IGNORE INTO user_ai_settings (username) VALUES ('admin')"
            )
            conn.commit()
            logger.debug("디폴트 'admin' 사용자 및 AI 설정 무결성 보장 완료")
        except Exception as e:
            logger.error("디폴트 사용자 생성 실패: %s", e)

    # ──────────────────────────────────────────
    # 사업자 프로필 CRUD
    # ──────────────────────────────────────────

    def add_business(self, profile: BusinessProfile, username: str = "admin") -> None:
        """
        사업자 프로필을 추가합니다.
        동일한 biz_id가 존재하면 덮어씁니다 (UPSERT).
        또한 등록한 사용자를 해당 회사의 'owner'로 연결 테이블(business_members)에 등록합니다.

        Args:
            profile: BusinessProfile 객체
            username: 소유자 사용자명
        """
        conn = self._ensure_connection()
        data = profile.to_dict()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        data["created_at"] = data.get("created_at") or now
        data["updated_at"] = now
        
        db_data = data.copy()
        if "username" in db_data:
            del db_data["username"]
        db_data["is_shared"] = 1 if db_data.get("is_shared") else 0
        db_data["has_sanctions"] = 1 if db_data.get("has_sanctions") else 0

        # 신규 필드 확보
        website_url = db_data.get("website_url")
        intro_file_url = db_data.get("intro_file_url")
        social_links = db_data.get("social_links")

        try:
            # 안전한 DB 호환성을 위해 SELECT 분기 처리
            cursor = conn.execute(
                "SELECT COUNT(*) FROM business_profiles WHERE biz_id = ?",
                (profile.biz_id,),
            )
            exists = cursor.fetchone()[0] > 0

            # 트랜잭션 수동 시작
            conn.execute("BEGIN TRANSACTION")

            if exists:
                conn.execute(
                    """
                    UPDATE business_profiles SET
                        company_name = ?,
                        ceo_name = ?,
                        business_types = ?,
                        licenses = ?,
                        regions = ?,
                        past_projects = ?,
                        annual_revenue = ?,
                        employee_count = ?,
                        keywords = ?,
                        min_budget = ?,
                        max_budget = ?,
                        credit_rating = ?,
                        company_type = ?,
                        has_sanctions = ?,
                        is_shared = ?,
                        website_url = ?,
                        intro_file_url = ?,
                        social_links = ?,
                        updated_at = ?
                    WHERE biz_id = ?
                    """,
                    (
                        db_data["company_name"],
                        db_data["ceo_name"],
                        db_data["business_types"],
                        db_data["licenses"],
                        db_data["regions"],
                        db_data["past_projects"],
                        db_data["annual_revenue"],
                        db_data["employee_count"],
                        db_data["keywords"],
                        db_data["min_budget"],
                        db_data["max_budget"],
                        db_data["credit_rating"],
                        db_data["company_type"],
                        db_data["has_sanctions"],
                        db_data["is_shared"],
                        website_url,
                        intro_file_url,
                        social_links,
                        db_data["updated_at"],
                        profile.biz_id
                    ),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO business_profiles
                        (biz_id, company_name, ceo_name, business_types, licenses,
                         regions, past_projects, annual_revenue, employee_count,
                         keywords, min_budget, max_budget, credit_rating, company_type,
                         has_sanctions, is_shared, website_url, intro_file_url, social_links,
                         created_at, updated_at)
                    VALUES
                        (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        profile.biz_id,
                        db_data["company_name"],
                        db_data["ceo_name"],
                        db_data["business_types"],
                        db_data["licenses"],
                        db_data["regions"],
                        db_data["past_projects"],
                        db_data["annual_revenue"],
                        db_data["employee_count"],
                        db_data["keywords"],
                        db_data["min_budget"],
                        db_data["max_budget"],
                        db_data["credit_rating"],
                        db_data["company_type"],
                        db_data["has_sanctions"],
                        db_data["is_shared"],
                        website_url,
                        intro_file_url,
                        social_links,
                        db_data["created_at"],
                        db_data["updated_at"]
                    ),
                )

            # 소유자 결정: profile.username이 우선, 없거나 admin이면 매개변수 username 사용
            owner_username = username
            if profile.username and profile.username != "admin":
                owner_username = profile.username

            # 멤버 연결 관계 등록 (owner로 등록)
            conn.execute(
                """
                INSERT OR IGNORE INTO business_members (biz_id, username, role)
                VALUES (?, ?, 'owner')
                """,
                (profile.biz_id, owner_username),
            )

            conn.execute("COMMIT")
            logger.info("사업자 프로필 및 소유자 등록 완료: %s (%s) [유저: %s]", profile.company_name, profile.biz_id, owner_username)
        except Exception as e:
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass
            logger.error("사업자 프로필 저장 실패: %s (오류: %s)", profile.biz_id, e)
            raise e

    def get_business(self, biz_id: str, username: Optional[str] = None) -> Optional[BusinessProfile]:
        """
        사업자등록번호로 프로필을 조회합니다.
        username이 제공되면 해당 사용자가 회사의 멤버인지 확인합니다.

        Args:
            biz_id: 사업자등록번호
            username: 사용자명 (선택)

        Returns:
            BusinessProfile 객체 또는 None
        """
        conn = self._ensure_connection()
        try:
            if username:
                cursor = conn.execute(
                    "SELECT COUNT(*) FROM business_members WHERE biz_id = ? AND username = ?",
                    (biz_id, username)
                )
                if cursor.fetchone()[0] == 0:
                    logger.warning("사업자 프로필 권한 없음: %s [유저: %s]", biz_id, username)
                    return None

            cursor = conn.execute(
                "SELECT * FROM business_profiles WHERE biz_id = ?", (biz_id,)
            )
            row = cursor.fetchone()
            if row:
                d = dict(row)
                d["username"] = username or "admin"
                return BusinessProfile.from_dict(d)
            return None
        except Exception as e:
            logger.error("사업자 프로필 조회 실패: %s (오류: %s)", biz_id, e)
            return None

    def get_businesses(self, username: str = "admin") -> list[BusinessProfile]:
        """
        특정 사용자가 소속된 전체 사업자 프로필 목록을 조회합니다.

        Args:
            username: 사용자명

        Returns:
            BusinessProfile 리스트
        """
        conn = self._ensure_connection()
        try:
            cursor = conn.execute(
                """
                SELECT p.* FROM business_profiles p
                JOIN business_members m ON p.biz_id = m.biz_id
                WHERE m.username = ?
                ORDER BY p.updated_at DESC
                """,
                (username,)
            )
            profiles = []
            for row in cursor.fetchall():
                d = dict(row)
                d["username"] = username
                profiles.append(BusinessProfile.from_dict(d))
            return profiles
        except Exception as e:
            logger.error("사업자 프로필 목록 조회 실패 [유저: %s]: %s", username, e)
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

        db_data = data.copy()
        if "username" in db_data:
            del db_data["username"]
        db_data["is_shared"] = 1 if db_data.get("is_shared") else 0
        db_data["has_sanctions"] = 1 if db_data.get("has_sanctions") else 0

        # 신규 필드 확보
        website_url = db_data.get("website_url")
        intro_file_url = db_data.get("intro_file_url")
        social_links = db_data.get("social_links")

        try:
            cursor = conn.execute(
                """
                UPDATE business_profiles SET
                    company_name = ?,
                    ceo_name = ?,
                    business_types = ?,
                    licenses = ?,
                    regions = ?,
                    past_projects = ?,
                    annual_revenue = ?,
                    employee_count = ?,
                    keywords = ?,
                    min_budget = ?,
                    max_budget = ?,
                    credit_rating = ?,
                    company_type = ?,
                    has_sanctions = ?,
                    is_shared = ?,
                    website_url = ?,
                    intro_file_url = ?,
                    social_links = ?,
                    updated_at = ?
                WHERE biz_id = ?
                """,
                (
                    db_data["company_name"],
                    db_data["ceo_name"],
                    db_data["business_types"],
                    db_data["licenses"],
                    db_data["regions"],
                    db_data["past_projects"],
                    db_data["annual_revenue"],
                    db_data["employee_count"],
                    db_data["keywords"],
                    db_data["min_budget"],
                    db_data["max_budget"],
                    db_data["credit_rating"],
                    db_data["company_type"],
                    db_data["has_sanctions"],
                    db_data["is_shared"],
                    website_url,
                    intro_file_url,
                    social_links,
                    db_data["updated_at"],
                    profile.biz_id
                ),
            )
            conn.commit()
            if cursor.rowcount > 0:
                logger.info("사업자 프로필 수정 완료: %s", profile.biz_id)
                return True
            else:
                logger.warning("수정할 사업자 프로필을 찾을 수 없습니다: %s", profile.biz_id)
                return False
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.error("사업자 프로필 수정 실패: %s (오류: %s)", profile.biz_id, e)
            return False

    def delete_business(self, biz_id: str, username: str = "admin") -> bool:
        """
        사업자 프로필을 삭제합니다 (owner 권한 필요).

        Args:
            biz_id: 사업자등록번호
            username: 사용자명

        Returns:
            삭제 성공 여부
        """
        conn = self._ensure_connection()
        try:
            # 권한 체크
            cursor = conn.execute(
                "SELECT role FROM business_members WHERE biz_id = ? AND username = ?",
                (biz_id, username),
            )
            row = cursor.fetchone()
            if not row or row["role"] != "owner":
                logger.warning("사업자 프로필 삭제 권한 없음 (owner가 아님): %s [유저: %s]", biz_id, username)
                return False

            cursor = conn.execute(
                "DELETE FROM business_profiles WHERE biz_id = ?", (biz_id,)
            )
            conn.commit()
            if cursor.rowcount > 0:
                logger.info("사업자 프로필 삭제 완료: %s [유저: %s]", biz_id, username)
                return True
            else:
                logger.warning("삭제할 사업자 프로필을 찾을 수 없습니다: %s", biz_id)
                return False
        except Exception as e:
            conn.rollback()
            logger.error("사업자 프로필 삭제 실패: %s [유저: %s] (오류: %s)", biz_id, username, e)
            return False

    # ──────────────────────────────────────────
    # 다중 회사 조직 및 멤버(직원) 관리
    # ──────────────────────────────────────────

    def get_user_companies(self, username: str) -> list[dict]:
        """사용자가 소속된 모든 회사 및 멤버 권한 목록을 조회합니다."""
        conn = self._ensure_connection()
        try:
            cursor = conn.execute(
                """
                SELECT m.biz_id, m.role, m.joined_at, p.company_name, p.ceo_name
                FROM business_members m
                JOIN business_profiles p ON m.biz_id = p.biz_id
                WHERE m.username = ?
                ORDER BY m.joined_at DESC
                """,
                (username,)
            )
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error("유저 소속 회사 목록 조회 실패 [유저: %s]: %s", username, e)
            return []

    def add_business_member(self, biz_id: str, username: str, role: str = "member") -> bool:
        """회사에 직원을 추가(초대)합니다."""
        conn = self._ensure_connection()
        try:
            conn.execute(
                """
                INSERT INTO business_members (biz_id, username, role)
                VALUES (?, ?, ?)
                """,
                (biz_id, username, role),
            )
            conn.commit()
            logger.info("회사 멤버 추가 성공: %s [유저: %s, 역할: %s]", biz_id, username, role)
            return True
        except Exception as e:
            conn.rollback()
            logger.error("회사 멤버 추가 실패: %s [유저: %s] (오류: %s)", biz_id, username, e)
            return False

    def get_business_members(self, biz_id: str) -> list[dict]:
        """회사의 전체 소속 멤버 목록을 조회합니다."""
        conn = self._ensure_connection()
        try:
            cursor = conn.execute(
                """
                SELECT m.id, m.biz_id, m.username, m.role, m.joined_at, u.email
                FROM business_members m
                JOIN users u ON m.username = u.username
                WHERE m.biz_id = ?
                ORDER BY CASE m.role WHEN 'owner' THEN 1 WHEN 'admin' THEN 2 ELSE 3 END, m.joined_at ASC
                """,
                (biz_id,)
            )
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error("회사 멤버 목록 조회 실패 [%s]: %s", biz_id, e)
            return []

    def update_business_member_role(self, biz_id: str, username: str, role: str) -> bool:
        """멤버의 권한(role)을 수정합니다."""
        conn = self._ensure_connection()
        try:
            cursor = conn.execute(
                """
                UPDATE business_members
                SET role = ?
                WHERE biz_id = ? AND username = ?
                """,
                (role, biz_id, username),
            )
            conn.commit()
            if cursor.rowcount > 0:
                logger.info("멤버 권한 변경 완료: %s [유저: %s, 역할: %s]", biz_id, username, role)
                return True
            return False
        except Exception as e:
            conn.rollback()
            logger.error("멤버 권한 변경 실패: %s [유저: %s] (오류: %s)", biz_id, username, e)
            return False

    def remove_business_member(self, biz_id: str, username: str) -> bool:
        """멤버를 제외(퇴사 처리)합니다."""
        conn = self._ensure_connection()
        try:
            cursor = conn.execute(
                """
                DELETE FROM business_members
                WHERE biz_id = ? AND username = ?
                """,
                (biz_id, username),
            )
            conn.commit()
            if cursor.rowcount > 0:
                logger.info("멤버 제외 완료: %s [유저: %s]", biz_id, username)
                return True
            return False
        except Exception as e:
            conn.rollback()
            logger.error("멤버 제외 실패: %s [유저: %s] (오류: %s)", biz_id, username, e)
            return False

    def get_business_user_role(self, biz_id: str, username: str) -> Optional[str]:
        """특정 유저가 특정 회사에 가진 권한을 조회합니다."""
        conn = self._ensure_connection()
        try:
            cursor = conn.execute(
                "SELECT role FROM business_members WHERE biz_id = ? AND username = ?",
                (biz_id, username),
            )
            row = cursor.fetchone()
            return row["role"] if row else None
        except Exception as e:
            logger.error("유저 회사 권한 조회 실패: %s [유저: %s] (오류: %s)", biz_id, username, e)
            return None

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

        try:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            data_list = []
            for bid in bids:
                data = bid.to_dict()
                data["collected_at"] = data.get("collected_at") or now
                data_list.append(data)

            # 저장 전 건수를 기록하여 실제 저장 건수 계산
            before_count = conn.execute(
                "SELECT COUNT(*) FROM bid_announcements"
            ).fetchone()[0]

            conn.executemany(
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
                data_list,
            )
            conn.commit()

            after_count = conn.execute(
                "SELECT COUNT(*) FROM bid_announcements"
            ).fetchone()[0]
            saved_count = after_count - before_count

            logger.info("입찰공고 저장 완료: %d건 (전체 %d건 중)", saved_count, len(bids))
            return saved_count

        except Exception as e:
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
        except Exception as e:
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
        except Exception as e:
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
        except Exception as e:
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

        try:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            data_list = []
            for award in awards:
                data = award.to_dict()
                data["collected_at"] = data.get("collected_at") or now
                data_list.append(data)

            before_count = conn.execute(
                "SELECT COUNT(*) FROM award_infos"
            ).fetchone()[0]

            # id 필드는 AUTOINCREMENT이므로 dict에서 제외하지 않아도
            # INSERT 컬럼 목록에 포함되지 않으므로 안전
            conn.executemany(
                """
                INSERT OR IGNORE INTO award_infos
                    (bid_ntce_no, bid_title, winner_name, award_amount,
                     bid_rate, award_date, budget, collected_at)
                VALUES
                    (:bid_ntce_no, :bid_title, :winner_name, :award_amount,
                     :bid_rate, :award_date, :budget, :collected_at)
                """,
                data_list,
            )
            conn.commit()

            after_count = conn.execute(
                "SELECT COUNT(*) FROM award_infos"
            ).fetchone()[0]
            saved_count = after_count - before_count

            logger.info("낙찰정보 저장 완료: %d건 (전체 %d건 중)", saved_count, len(awards))
            return saved_count

        except Exception as e:
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
        except Exception as e:
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
        except Exception as e:
            logger.error("낙찰정보 검색 실패 (키워드: %s): %s", keyword, e)
            return []

    def get_awards_by_winner(self, winner_name: str, limit: int = 50) -> list[AwardInfo]:
        """
        업체명으로 낙찰 이력을 조회합니다.

        경쟁사 수주 패턴 분석에 사용됩니다.

        Args:
            winner_name: 낙찰 업체명 (부분 일치)
            limit: 최대 반환 건수

        Returns:
            AwardInfo 리스트
        """
        conn = self._ensure_connection()
        try:
            cursor = conn.execute(
                """
                SELECT * FROM award_infos
                WHERE winner_name LIKE ?
                ORDER BY award_date DESC
                LIMIT ?
                """,
                (f"%{winner_name}%", limit),
            )
            return [AwardInfo.from_dict(dict(row)) for row in cursor.fetchall()]
        except Exception as e:
            logger.error("업체별 낙찰정보 조회 실패 (업체: %s): %s", winner_name, e)
            return []

    def get_awards_by_org(self, org_name: str, limit: int = 100) -> list[AwardInfo]:
        """
        발주기관명으로 낙찰 이력을 조회합니다.

        발주기관 정책 방향 분석에 사용됩니다.

        Args:
            org_name: 발주기관명 (부분 일치)
            limit: 최대 반환 건수

        Returns:
            AwardInfo 리스트
        """
        conn = self._ensure_connection()
        try:
            cursor = conn.execute(
                """
                SELECT a.* FROM award_infos a
                JOIN bid_announcements b ON a.bid_ntce_no = b.bid_ntce_no
                WHERE b.org_name LIKE ?
                ORDER BY a.award_date DESC
                LIMIT ?
                """,
                (f"%{org_name}%", limit),
            )
            return [AwardInfo.from_dict(dict(row)) for row in cursor.fetchall()]
        except Exception as e:
            logger.error("기관별 낙찰정보 조회 실패 (기관: %s): %s", org_name, e)
            return []

    def get_bids_by_org(self, org_name: str, limit: int = 100) -> list[BidAnnouncement]:
        """
        발주기관명으로 공고 이력을 조회합니다.

        기관의 발주 패턴, 카테고리 변화 추적에 사용됩니다.

        Args:
            org_name: 발주기관명 (부분 일치)
            limit: 최대 반환 건수

        Returns:
            BidAnnouncement 리스트
        """
        conn = self._ensure_connection()
        try:
            cursor = conn.execute(
                """
                SELECT * FROM bid_announcements
                WHERE org_name LIKE ?
                ORDER BY collected_at DESC
                LIMIT ?
                """,
                (f"%{org_name}%", limit),
            )
            return [BidAnnouncement.from_dict(dict(row)) for row in cursor.fetchall()]
        except Exception as e:
            logger.error("기관별 공고 조회 실패 (기관: %s): %s", org_name, e)
            return []

    def get_awards_by_region(self, region: str, limit: int = 200) -> list[AwardInfo]:
        """
        지역별 낙찰 현황을 조회합니다.

        지역 트렌드 분석에 사용됩니다.

        Args:
            region: 지역명 (부분 일치)
            limit: 최대 반환 건수

        Returns:
            AwardInfo 리스트
        """
        conn = self._ensure_connection()
        try:
            cursor = conn.execute(
                """
                SELECT a.* FROM award_infos a
                JOIN bid_announcements b ON a.bid_ntce_no = b.bid_ntce_no
                WHERE b.region LIKE ?
                ORDER BY a.award_date DESC
                LIMIT ?
                """,
                (f"%{region}%", limit),
            )
            return [AwardInfo.from_dict(dict(row)) for row in cursor.fetchall()]
        except Exception as e:
            logger.error("지역별 낙찰정보 조회 실패 (지역: %s): %s", region, e)
            return []

    def get_award_stats(self, keyword: str = None, org_name: str = None) -> dict:
        """
        투찰률 및 낙찰금액 통계를 조회합니다.

        적정 투찰률 분석에 사용됩니다.

        Args:
            keyword: 공고명 키워드 (선택)
            org_name: 발주기관명 (선택)

        Returns:
            통계 딕셔너리 (avg_bid_rate, median_bid_rate, min/max, count 등)
        """
        conn = self._ensure_connection()
        try:
            conditions = ["a.bid_rate IS NOT NULL", "a.bid_rate > 0"]
            params = []

            if keyword:
                conditions.append("a.bid_title LIKE ?")
                params.append(f"%{keyword}%")
            if org_name:
                conditions.append("b.org_name LIKE ?")
                params.append(f"%{org_name}%")

            where_clause = " AND ".join(conditions)
            join_clause = "JOIN bid_announcements b ON a.bid_ntce_no = b.bid_ntce_no" if org_name else ""

            cursor = conn.execute(
                f"""
                SELECT
                    COUNT(*) as total_count,
                    AVG(a.bid_rate) as avg_bid_rate,
                    MIN(a.bid_rate) as min_bid_rate,
                    MAX(a.bid_rate) as max_bid_rate,
                    AVG(a.award_amount) as avg_award_amount,
                    MIN(a.award_amount) as min_award_amount,
                    MAX(a.award_amount) as max_award_amount,
                    SUM(a.award_amount) as total_award_amount
                FROM award_infos a
                {join_clause}
                WHERE {where_clause}
                """,
                params,
            )
            row = cursor.fetchone()
            if not row or row["total_count"] == 0:
                return {"total_count": 0}

            # 중앙값 계산
            median_cursor = conn.execute(
                f"""
                SELECT a.bid_rate FROM award_infos a
                {join_clause}
                WHERE {where_clause}
                ORDER BY a.bid_rate
                LIMIT 1 OFFSET ?
                """,
                params + [row["total_count"] // 2],
            )
            median_row = median_cursor.fetchone()

            return {
                "total_count": row["total_count"],
                "avg_bid_rate": round(row["avg_bid_rate"], 2) if row["avg_bid_rate"] else 0,
                "median_bid_rate": round(median_row["bid_rate"], 2) if median_row else 0,
                "min_bid_rate": round(row["min_bid_rate"], 2) if row["min_bid_rate"] else 0,
                "max_bid_rate": round(row["max_bid_rate"], 2) if row["max_bid_rate"] else 0,
                "avg_award_amount": int(row["avg_award_amount"]) if row["avg_award_amount"] else 0,
                "min_award_amount": int(row["min_award_amount"]) if row["min_award_amount"] else 0,
                "max_award_amount": int(row["max_award_amount"]) if row["max_award_amount"] else 0,
                "total_award_amount": int(row["total_award_amount"]) if row["total_award_amount"] else 0,
            }
        except Exception as e:
            logger.error("낙찰 통계 조회 실패: %s", e)
            return {"total_count": 0}

    def get_competitor_market_share(self, limit: int = 5) -> list[dict]:
        """
        최근 낙찰 정보를 기반으로 경쟁사별 수주 점유율 및 수주액 통계를 계산합니다.
        """
        conn = self._ensure_connection()
        try:
            cursor = conn.execute(
                """
                SELECT 
                    winner_name,
                    COUNT(*) as win_count,
                    SUM(award_amount) as total_award_amount,
                    AVG(bid_rate) as avg_bid_rate
                FROM award_infos
                WHERE winner_name IS NOT NULL AND winner_name != ''
                GROUP BY winner_name
                ORDER BY win_count DESC, total_award_amount DESC
                LIMIT ?
                """,
                (limit,),
            )
            results = []
            for row in cursor.fetchall():
                d = dict(row)
                d["avg_bid_rate"] = round(d["avg_bid_rate"], 2) if d["avg_bid_rate"] else 0
                d["total_award_amount"] = int(d["total_award_amount"]) if d["total_award_amount"] else 0
                results.append(d)
            return results
        except Exception as e:
            logger.error("경쟁사 수주 시장 분석 실패: %s", e)
            return []

    def get_similar_bids_by_title(self, title: str, limit: int = 20) -> list[BidAnnouncement]:
        """
        제목으로 유사 공고를 검색합니다.

        전년도 동일/유사 사업 자동 발견에 사용됩니다.

        Args:
            title: 현재 공고 제목 (핵심 키워드 추출 후 LIKE 검색)
            limit: 최대 반환 건수

        Returns:
            BidAnnouncement 리스트
        """
        conn = self._ensure_connection()
        try:
            # 제목에서 핵심 키워드 추출 (2글자 이상 단어)
            import re
            words = re.findall(r'[가-힣]{2,}|[A-Za-z]{2,}', title)
            if not words:
                return []

            # 상위 3개 키워드로 검색
            conditions = []
            params = []
            for word in words[:3]:
                conditions.append("title LIKE ?")
                params.append(f"%{word}%")

            where_clause = " OR ".join(conditions)
            params.append(limit)

            cursor = conn.execute(
                f"""
                SELECT * FROM bid_announcements
                WHERE ({where_clause})
                ORDER BY collected_at DESC
                LIMIT ?
                """,
                params,
            )
            return [BidAnnouncement.from_dict(dict(row)) for row in cursor.fetchall()]
        except Exception as e:
            logger.error("유사 공고 검색 실패: %s", e)
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

        try:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            data_list = []
            for article in articles:
                data = article.to_dict()
                data["collected_at"] = data.get("collected_at") or now
                data_list.append(data)

            before_count = conn.execute(
                "SELECT COUNT(*) FROM news_articles"
            ).fetchone()[0]

            conn.executemany(
                """
                INSERT OR IGNORE INTO news_articles
                    (title, description, link, pub_date, search_query,
                     related_bid_no, collected_at)
                VALUES
                    (:title, :description, :link, :pub_date, :search_query,
                     :related_bid_no, :collected_at)
                """,
                data_list,
            )
            conn.commit()

            after_count = conn.execute(
                "SELECT COUNT(*) FROM news_articles"
            ).fetchone()[0]
            saved_count = after_count - before_count

            logger.info("뉴스기사 저장 완료: %d건 (전체 %d건 중)", saved_count, len(articles))
            return saved_count

        except Exception as e:
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
        except Exception as e:
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

        except Exception as e:
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
        except Exception as e:
            conn.rollback()
            logger.error("분석결과 삭제 실패: %s", e)
            return False

    def delete_all_analyses(self) -> int:
        """모든 분석결과를 삭제합니다."""
        conn = self._ensure_connection()
        try:
            cursor = conn.execute("DELETE FROM analysis_results")
            conn.commit()
            count = cursor.rowcount
            logger.info("분석결과 전체 삭제: %d건", count)
            return count
        except Exception as e:
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
        except Exception as e:
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
        except Exception as e:
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
            "users",
            "user_favorites"
        }

        for table in _ALLOWED_TABLES:
            try:
                # 테이블명은 화이트리스트에서만 가져오므로 파라미터화 불필요
                # PostgreSQL과 SQLite 모두 호환되는 표준 SQL (대괄호 없이)
                cursor = conn.execute(f"SELECT COUNT(*) FROM {table}")
                row = cursor.fetchone()
                stats[table] = row[0] if row else 0
            except Exception:
                stats[table] = -1

        return stats

    # ──────────────────────────────────────────
    # 회원(users) 관리 CRUD
    # ──────────────────────────────────────────

    def add_user(self, username: str, password_hash: str, email: Optional[str] = None) -> None:
        """
        신규 회원을 등록하고 디폴트 AI 설정을 생성합니다.
        """
        conn = self._ensure_connection()
        try:
            conn.execute("BEGIN TRANSACTION")
            conn.execute(
                """
                INSERT INTO users (username, password_hash, email)
                VALUES (?, ?, ?)
                """,
                (username, password_hash, email),
            )
            conn.execute(
                "INSERT OR IGNORE INTO user_ai_settings (username) VALUES (?)",
                (username,),
            )
            conn.commit()
            logger.info("회원 등록 및 AI 설정 완료: %s", username)
        except Exception as e:
            conn.rollback()
            logger.error("회원 등록 실패: %s (오류: %s)", username, e)
            raise

    def get_user(self, username: str) -> Optional[dict]:
        """
        사용자명으로 회원 정보를 조회합니다.
        """
        conn = self._ensure_connection()
        try:
            cursor = conn.execute(
                "SELECT * FROM users WHERE username = ?", (username,)
            )
            row = cursor.fetchone()
            if row:
                return dict(row)
            return None
        except Exception as e:
            logger.error("회원 정보 조회 실패: %s (오류: %s)", username, e)
            return None

    # ──────────────────────────────────────────
    # 사용자 관심공고(user_favorites) CRUD
    # ──────────────────────────────────────────

    def add_favorite(self, username: str, bid_ntce_no: str, status: str = 'reviewing',
                     memo: Optional[str] = None, partners: Optional[list] = None,
                     checklist: Optional[list] = None, title: Optional[str] = None,
                     org_name: Optional[str] = None, budget: Optional[int] = None,
                     bid_close_dt: Optional[str] = None) -> None:
        """
        관심공고를 추가합니다. 이미 존재하면 덮어씁니다 (UPSERT).
        bid_announcements에 공고가 없어도 저장됩니다 (외부 공고번호 지원).
        """
        conn = self._ensure_connection()
        try:
            # 외래키 제약조건(FK) 만족을 위해 bid_announcements에 공고 정보가 없으면 선제 삽입
            ph = "%s" if self.is_postgres else "?"
            cursor_check = conn.execute(
                f"SELECT COUNT(*) FROM bid_announcements WHERE bid_ntce_no = {ph}",
                (bid_ntce_no,),
            )
            if cursor_check.fetchone()[0] == 0:
                conn.execute(
                    f"""
                    INSERT INTO bid_announcements 
                        (bid_ntce_no, title, org_name, budget, bid_close_dt)
                    VALUES ({ph}, {ph}, {ph}, {ph}, {ph})
                    """,
                    (
                        bid_ntce_no,
                        title or "사용자 등록 외부 공고",
                        org_name or "외부 기관",
                        budget or 0,
                        bid_close_dt or "",
                    ),
                )

            partners_json = _dump_json_field(partners)
            checklist_json = _dump_json_field(checklist)



            # DB 호환성을 위해 SELECT 분기 처리
            cursor = conn.execute(
                "SELECT COUNT(*) FROM user_favorites WHERE username = ? AND bid_ntce_no = ?",
                (username, bid_ntce_no),
            )
            exists = cursor.fetchone()[0] > 0

            if exists:
                conn.execute(
                    """
                    UPDATE user_favorites SET
                        status = ?,
                        memo = ?,
                        partners = ?,
                        checklist = ?
                    WHERE username = ? AND bid_ntce_no = ?
                    """,
                    (status, memo, partners_json, checklist_json, username, bid_ntce_no),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO user_favorites
                        (username, bid_ntce_no, status, memo, partners, checklist, title, org_name, budget, bid_close_dt)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (username, bid_ntce_no, status, memo, partners_json, checklist_json,
                     title, org_name, budget, bid_close_dt),
                )
            conn.commit()
            logger.info("관심공고 저장 완료: %s [유저: %s]", bid_ntce_no, username)
        except Exception as e:
            conn.rollback()
            logger.error("관심공고 저장 실패: %s [유저: %s] (오류: %s)", bid_ntce_no, username, e)
            raise

    def get_favorites(self, username: str) -> list[dict]:
        """
        특정 사용자의 전체 관심공고 목록을 조회합니다.
        (입찰공고 테이블과 조인하여 제목, 발주기관, 마감일 등의 정보를 함께 반환합니다.)
        """
        conn = self._ensure_connection()
        try:
            cursor = conn.execute(
                """
                SELECT uf.id, uf.username, uf.bid_ntce_no, uf.status, uf.memo,
                       uf.partners, uf.checklist, uf.added_at,
                       uf.analysis_done, uf.analysis_summary,
                       COALESCE(uf.title, ba.title, uf.bid_ntce_no) as title,
                       COALESCE(uf.org_name, ba.org_name, '') as org_name,
                       COALESCE(uf.budget, ba.budget) as budget,
                       COALESCE(uf.bid_close_dt, ba.bid_close_dt) as bid_close_dt
                FROM user_favorites uf
                LEFT JOIN bid_announcements ba ON uf.bid_ntce_no = ba.bid_ntce_no
                WHERE uf.username = ?
                ORDER BY uf.added_at DESC
                """,
                (username,),
            )
            result = []
            for row in cursor.fetchall():
                d = dict(row)
                d["partners"] = _parse_json_field(d.get("partners"))
                d["checklist"] = _parse_json_field(d.get("checklist"))
                result.append(d)
            return result
        except Exception as e:
            logger.error("관심공고 목록 조회 실패 [유저: %s]: %s", username, e)
            return []

    def get_favorite(self, username: str, bid_ntce_no: str) -> Optional[dict]:
        """
        단일 관심공고 내역을 조회합니다.
        """
        conn = self._ensure_connection()
        try:
            cursor = conn.execute(
                """
                SELECT uf.id, uf.username, uf.bid_ntce_no, uf.status, uf.memo,
                       uf.partners, uf.checklist, uf.added_at,
                       uf.analysis_done, uf.analysis_summary,
                       COALESCE(uf.title, ba.title, uf.bid_ntce_no) as title,
                       COALESCE(uf.org_name, ba.org_name, '') as org_name,
                       COALESCE(uf.budget, ba.budget) as budget,
                       COALESCE(uf.bid_close_dt, ba.bid_close_dt) as bid_close_dt
                FROM user_favorites uf
                LEFT JOIN bid_announcements ba ON uf.bid_ntce_no = ba.bid_ntce_no
                WHERE uf.username = ? AND uf.bid_ntce_no = ?
                """,
                (username, bid_ntce_no),
            )
            row = cursor.fetchone()
            if row:
                d = dict(row)
                d["partners"] = _parse_json_field(d.get("partners"))
                d["checklist"] = _parse_json_field(d.get("checklist"))
                return d
            return None
        except Exception as e:
            logger.error("관심공고 개별 조회 실패: %s [유저: %s] (오류: %s)", bid_ntce_no, username, e)
            return None

    def update_favorite(self, username: str, bid_ntce_no: str, status: Optional[str] = None,
                        memo: Optional[str] = None, partners: Optional[list] = None,
                        checklist: Optional[list] = None,
                        analysis_done: Optional[bool] = None,
                        analysis_summary: Optional[str] = None,
                        title: Optional[str] = None,
                        org_name: Optional[str] = None) -> bool:
        """
        관심공고 상세 내용을 업데이트합니다.
        존재하지 않는 경우 자동으로 추가(UPSERT) 합니다.
        """
        conn = self._ensure_connection()

        # 존재 여부 확인 - 없으면 자동 추가
        exists = conn.execute(
            "SELECT COUNT(*) FROM user_favorites WHERE username = ? AND bid_ntce_no = ?",
            (username, bid_ntce_no)
        ).fetchone()[0] > 0

        if not exists:
            # 없으면 add_favorite로 UPSERT
            try:
                self.add_favorite(
                    username=username,
                    bid_ntce_no=bid_ntce_no,
                    status=status or 'reviewing',
                    memo=memo,
                    partners=partners,
                    checklist=checklist
                )
                logger.info("관심공고 자동 추가 후 업데이트: %s [유저: %s]", bid_ntce_no, username)
                return True
            except Exception as e:
                logger.error("관심공고 자동 추가 실패: %s [유저: %s] (오류: %s)", bid_ntce_no, username, e)
                return False

        # 업데이트 쿼리를 동적으로 구성
        updates = []
        params = []
        if status is not None:
            updates.append("status = ?")
            params.append(status)
        if memo is not None:
            updates.append("memo = ?")
            params.append(memo)
        if partners is not None:
            updates.append("partners = ?")
            params.append(_dump_json_field(partners))
        if checklist is not None:
            updates.append("checklist = ?")
            params.append(_dump_json_field(checklist))
        # analysis 필드 (컬럼이 없으면 무시)
        if analysis_done is not None:
            try:
                conn.execute("SELECT analysis_done FROM user_favorites LIMIT 0")
                updates.append("analysis_done = ?")
                params.append(1 if analysis_done else 0)
            except Exception:
                pass  # 컬럼 없으면 무시
        if analysis_summary is not None:
            try:
                conn.execute("SELECT analysis_summary FROM user_favorites LIMIT 0")
                updates.append("analysis_summary = ?")
                params.append(analysis_summary)
            except Exception:
                pass  # 컬럼 없으면 무시
        # title/org_name 필드 (컬럼이 없으면 무시)
        if title is not None:
            try:
                conn.execute("SELECT title FROM user_favorites LIMIT 0")
                updates.append("title = ?")
                params.append(title)
            except Exception:
                pass
        if org_name is not None:
            try:
                conn.execute("SELECT org_name FROM user_favorites LIMIT 0")
                updates.append("org_name = ?")
                params.append(org_name)
            except Exception:
                pass

        if not updates:
            # 업데이트할 내용이 없어도 존재하면 True 반환
            return True

        params.extend([username, bid_ntce_no])
        sql = f"UPDATE user_favorites SET {', '.join(updates)} WHERE username = ? AND bid_ntce_no = ?"

        try:
            cursor = conn.execute(sql, tuple(params))
            conn.commit()
            if cursor.rowcount > 0:
                logger.info("관심공고 업데이트 완료: %s [유저: %s]", bid_ntce_no, username)
                return True
            return False
        except Exception as e:
            conn.rollback()
            logger.error("관심공고 업데이트 실패: %s [유저: %s] (오류: %s)", bid_ntce_no, username, e)
            return False

    def delete_favorite(self, username: str, bid_ntce_no: str) -> bool:
        """
        관심공고를 삭제합니다.
        """
        conn = self._ensure_connection()
        try:
            cursor = conn.execute(
                "DELETE FROM user_favorites WHERE username = ? AND bid_ntce_no = ?",
                (username, bid_ntce_no),
            )
            conn.commit()
            if cursor.rowcount > 0:
                logger.info("관심공고 삭제 완료: %s [유저: %s]", bid_ntce_no, username)
                return True
            return False
        except Exception as e:
            conn.rollback()
            logger.error("관심공고 삭제 실패: %s [유저: %s] (오류: %s)", bid_ntce_no, username, e)
            return False

    # ──────────────────────────────────────────
    # 개인 AI 설정 (user_ai_settings) CRUD
    # ──────────────────────────────────────────

    def get_user_ai_settings(self, username: str) -> Optional[dict]:
        """
        특정 유저의 개인 AI 에이전트 가중치 및 설정을 조회합니다.
        """
        conn = self._ensure_connection()
        try:
            cursor = conn.execute(
                "SELECT * FROM user_ai_settings WHERE username = ?", (username,)
            )
            row = cursor.fetchone()
            if row:
                d = dict(row)
                d["custom_keywords"] = _parse_json_field(d.get("custom_keywords"))
                return d
            return None
        except Exception as e:
            logger.error("AI 설정 조회 실패 [유저: %s]: %s", username, e)
            return None

    def save_user_ai_settings(self, username: str, settings: dict) -> bool:
        """
        유저의 개인 AI 에이전트 투찰 가중치 및 페르소나 설정을 저장/업데이트합니다.
        """
        conn = self._ensure_connection()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            conn.execute(
                """
                INSERT INTO user_ai_settings 
                    (username, bid_target, relevance_weight, capacity_weight, credit_weight, ai_persona, custom_keywords, updated_at)
                VALUES 
                    (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(username) DO UPDATE SET
                    bid_target = excluded.bid_target,
                    relevance_weight = excluded.relevance_weight,
                    capacity_weight = excluded.capacity_weight,
                    credit_weight = excluded.credit_weight,
                    ai_persona = excluded.ai_persona,
                    custom_keywords = excluded.custom_keywords,
                    updated_at = excluded.updated_at
                """,
                (
                    username,
                    settings.get("bid_target", "stable"),
                    settings.get("relevance_weight", 0.35),
                    settings.get("capacity_weight", 0.35),
                    settings.get("credit_weight", 0.30),
                    settings.get("ai_persona", "strategic"),
                    _dump_json_field(settings.get("custom_keywords", [])),
                    now
                )
            )
            conn.commit()
            logger.info("AI 설정 저장 완료 [유저: %s]", username)
            return True
        except Exception as e:
            conn.rollback()
            logger.error("AI 설정 저장 실패 [유저: %s]: %s", username, e)
            return False

    # ──────────────────────────────────────────
    # 관리자 운영 통계 및 통합 제어
    # ──────────────────────────────────────────

    def get_admin_stats(self) -> dict:
        """
        전체 가입 회원, 회사, 입찰공고 및 다중 협업사 매칭 수 등 시스템 운영 통계를 집계합니다.
        """
        conn = self._ensure_connection()
        stats = {}
        try:
            stats["total_users"] = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            stats["total_companies"] = conn.execute("SELECT COUNT(*) FROM business_profiles").fetchone()[0]
            stats["total_bids"] = conn.execute("SELECT COUNT(*) FROM bid_announcements").fetchone()[0]
            stats["total_favorites"] = conn.execute("SELECT COUNT(*) FROM user_favorites").fetchone()[0]
            
            # 협업 연계 카운트 (동일 공고번호에 2명 이상의 유저가 관심등록한 건수)
            collab_cursor = conn.execute(
                "SELECT COUNT(DISTINCT bid_ntce_no) FROM user_favorites GROUP BY bid_ntce_no HAVING COUNT(username) >= 2"
            )
            stats["total_collaborations"] = len(collab_cursor.fetchall())
            return stats
        except Exception as e:
            logger.error("관리자 통계 집계 실패: %s", e)
            return {
                "total_users": 0, "total_companies": 0, "total_bids": 0, 
                "total_favorites": 0, "total_collaborations": 0
            }

    def get_all_users_for_admin(self) -> list[dict]:
        """
        관리자용 전체 회원 목록 및 에이전트 요약 정보를 조회합니다.
        """
        conn = self._ensure_connection()
        try:
            cursor = conn.execute(
                """
                SELECT u.username, u.email, u.is_admin, u.created_at, 
                       s.bid_target, s.ai_persona
                FROM users u
                LEFT JOIN user_ai_settings s ON u.username = s.username
                ORDER BY u.created_at DESC
                """
            )
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error("관리자용 전체 회원 목록 조회 실패: %s", e)
            return []

    def update_user_admin_flag(self, username: str, is_admin: bool) -> bool:
        """
        회원의 관리자 권한 여부(is_admin)를 변경합니다.
        """
        conn = self._ensure_connection()
        flag = 1 if is_admin else 0
        try:
            cursor = conn.execute(
                "UPDATE users SET is_admin = ? WHERE username = ?",
                (flag, username)
            )
            conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            conn.rollback()
            logger.error("관리자 권한 변경 실패 [유저: %s]: %s", username, e)
            return False

    def delete_user_by_admin(self, username: str) -> bool:
        """
        관리자가 특정 불량 사용자를 강제 탈퇴 처리합니다. (최고관리자 admin 제외)
        """
        conn = self._ensure_connection()
        if username == "admin":
            logger.warning("최고관리자 계정 'admin'은 삭제할 수 없습니다.")
            return False
        try:
            cursor = conn.execute(
                "DELETE FROM users WHERE username = ?", (username,)
            )
            conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            conn.rollback()
            logger.error("회원 강제 삭제 실패 [유저: %s]: %s", username, e)
            return False

    def update_user_profile(self, username: str, email: Optional[str]) -> bool:
        """
        회원의 이메일을 수정합니다.
        """
        conn = self._ensure_connection()
        try:
            cursor = conn.execute(
                "UPDATE users SET email = ? WHERE username = ?",
                (email, username)
            )
            conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            conn.rollback()
            logger.error("회원 프로필 수정 실패 [유저: %s]: %s", username, e)
            return False

    def change_user_password(self, username: str, new_password_hash: str) -> bool:
        """
        현재 로그인한 사용자의 비밀번호를 변경합니다.
        """
        conn = self._ensure_connection()
        try:
            cursor = conn.execute(
                "UPDATE users SET password_hash = ? WHERE username = ?",
                (new_password_hash, username)
            )
            conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            conn.rollback()
            logger.error("비밀번호 변경 실패 [유저: %s]: %s", username, e)
            return False

    def delete_user_self(self, username: str) -> bool:
        """
        사용자가 스스로 계정을 탈퇴 처리합니다. 관련 데이터(관심공고, AI설정, 소속 멤버 제거)도 함께 정리합니다.
        admin 계정은 탈퇴 불가.
        """
        conn = self._ensure_connection()
        if username == "admin":
            return False
        try:
            conn.execute("BEGIN TRANSACTION")
            conn.execute("DELETE FROM user_favorites WHERE username = ?", (username,))
            conn.execute("DELETE FROM user_ai_settings WHERE username = ?", (username,))
            conn.execute("DELETE FROM business_members WHERE username = ?", (username,))
            conn.execute("DELETE FROM users WHERE username = ?", (username,))
            conn.commit()
            logger.info("회원 자진 탈퇴 처리 완료: %s", username)
            return True
        except Exception as e:
            conn.rollback()
            logger.error("회원 자진 탈퇴 실패 [유저: %s]: %s", username, e)
            return False

    def delete_company_by_admin(self, biz_id: str) -> bool:
        """
        관리자가 불건전하거나 불필요한 회사 프로필을 강제 삭제 처리합니다.
        """
        conn = self._ensure_connection()
        try:
            conn.execute("BEGIN TRANSACTION")
            conn.execute("DELETE FROM business_members WHERE biz_id = ?", (biz_id,))
            cursor = conn.execute("DELETE FROM business_profiles WHERE biz_id = ?", (biz_id,))
            conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            conn.rollback()
            logger.error("회사 강제 삭제 실패 [회사ID: %s]: %s", biz_id, e)
            return False

    def get_all_companies_for_admin(self) -> list[dict]:
        """
        관리자용 등록된 전체 회사 현황과 소속 직원 규모를 조회합니다.
        """
        conn = self._ensure_connection()
        try:
            cursor = conn.execute(
                """
                SELECT p.biz_id, p.company_name, p.ceo_name, p.annual_revenue, p.employee_count, p.created_at,
                       (SELECT COUNT(*) FROM business_members m WHERE m.biz_id = p.biz_id) AS member_count
                FROM business_profiles p
                ORDER BY p.created_at DESC
                """
            )
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error("관리자용 전체 회사 목록 조회 실패: %s", e)
            return []

    def get_all_collaborations_for_admin(self) -> list[dict]:
        """
        공동 입찰 컨소시엄에 가담하여 협업 중인 공고 및 매칭 파트너 유저 목록을 일괄 모니터링합니다.
        """
        conn = self._ensure_connection()
        try:
            cursor = conn.execute(
                """
                SELECT f.bid_ntce_no, b.title AS bid_title, 
                       GROUP_CONCAT(f.username, ', ') AS user_list, 
                       COUNT(f.username) AS user_count
                FROM user_favorites f
                JOIN bid_announcements b ON f.bid_ntce_no = b.bid_ntce_no
                GROUP BY f.bid_ntce_no
                HAVING user_count >= 2
                ORDER BY user_count DESC
                """
            )
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error("관리자용 전체 협업 목록 조회 실패: %s", e)
            return []

    # ──────────────────────────────────────────
    # 사내 카페(커뮤니티) 관리 기능
    # ──────────────────────────────────────────

    def get_cafe_posts(self, biz_id: str, current_username: str = "") -> list[dict]:
        """특정 회사(biz_id) 소속 멤버들의 사내 카페 게시글 목록을 최신순으로 조회합니다."""
        conn = self._ensure_connection()
        try:
            cursor = conn.execute(
                """
                SELECT p.id, p.biz_id, p.username, p.title, p.content, p.created_at, p.updated_at, u.email,
                       (SELECT COUNT(*) FROM company_cafe_comments WHERE post_id = p.id) as comment_count,
                       (SELECT COUNT(*) FROM company_cafe_likes WHERE post_id = p.id) as like_count,
                       (SELECT COUNT(*) FROM company_cafe_likes WHERE post_id = p.id AND username = ?) as user_liked
                FROM company_cafe_posts p
                LEFT JOIN users u ON p.username = u.username
                WHERE p.biz_id = ?
                ORDER BY p.created_at DESC
                """,
                (current_username, biz_id)
            )
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error("사내 카페 게시글 목록 조회 실패 [회사 ID: %s]: %s", biz_id, e)
            return []

    def create_cafe_post(self, biz_id: str, username: str, title: str, content: str) -> Optional[dict]:
        """사내 카페에 새로운 게시글을 등록합니다."""
        conn = self._ensure_connection()
        try:
            if self.is_postgres:
                cursor = conn.execute(
                    """
                    INSERT INTO company_cafe_posts (biz_id, username, title, content)
                    VALUES (%s, %s, %s, %s)
                    RETURNING id
                    """,
                    (biz_id, username, title, content),
                )
                row_id = cursor.fetchone()
                new_id = row_id[0] if row_id else None
                conn.commit()
                if new_id is None:
                    return None
                # 새로 생성된 게시글 정보를 반환
                cursor = conn.execute(
                    """
                    SELECT p.id, p.biz_id, p.username, p.title, p.content, p.created_at, p.updated_at, u.email,
                           0 as comment_count,
                           0 as like_count,
                           0 as user_liked
                    FROM company_cafe_posts p
                    LEFT JOIN users u ON p.username = u.username
                    WHERE p.id = %s
                    """,
                    (new_id,)
                )
            else:
                cursor = conn.execute(
                    """
                    INSERT INTO company_cafe_posts (biz_id, username, title, content)
                    VALUES (?, ?, ?, ?)
                    """,
                    (biz_id, username, title, content),
                )
                new_id = cursor.lastrowid
                conn.commit()
                # 새로 생성된 게시글 정보를 반환
                cursor = conn.execute(
                    """
                    SELECT p.id, p.biz_id, p.username, p.title, p.content, p.created_at, p.updated_at, u.email,
                           0 as comment_count,
                           0 as like_count,
                           0 as user_liked
                    FROM company_cafe_posts p
                    LEFT JOIN users u ON p.username = u.username
                    WHERE p.id = ?
                    """,
                    (new_id,)
                )
            row = cursor.fetchone()
            return dict(row) if row else None
        except Exception as e:
            conn.rollback()
            logger.error("사내 카페 게시글 등록 실패 [회사 ID: %s, 유저: %s]: %s", biz_id, username, e)
            return None

    def delete_cafe_post(self, post_id: int, biz_id: str) -> bool:
        """사내 카페 게시글을 삭제합니다."""
        conn = self._ensure_connection()
        try:
            cursor = conn.execute(
                "DELETE FROM company_cafe_posts WHERE id = ? AND biz_id = ?",
                (post_id, biz_id),
            )
            conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            conn.rollback()
            logger.error("사내 카페 게시글 삭제 실패 [ID: %s, 회사 ID: %s]: %s", post_id, biz_id, e)
            return False

    def update_cafe_post(self, post_id: int, biz_id: str, username: str, title: str, content: str) -> bool:
        """사내 카페 게시글을 수정합니다. 작성자 본인만 수정 가능합니다."""
        conn = self._ensure_connection()
        try:
            cursor = conn.execute(
                """
                UPDATE company_cafe_posts
                SET title = ?, content = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND biz_id = ? AND username = ?
                """,
                (title, content, post_id, biz_id, username),
            )
            conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            conn.rollback()
            logger.error("사내 카페 게시글 수정 실패 [ID: %s, 유저: %s]: %s", post_id, username, e)
            return False

    def get_cafe_comments(self, post_id: int) -> list[dict]:
        """특정 게시글의 댓글 목록을 시간순으로 조회합니다."""
        conn = self._ensure_connection()
        try:
            cursor = conn.execute(
                """
                SELECT c.id, c.post_id, c.username, c.content, c.created_at, c.updated_at, u.email
                FROM company_cafe_comments c
                LEFT JOIN users u ON c.username = u.username
                WHERE c.post_id = ?
                ORDER BY c.created_at ASC
                """,
                (post_id,)
            )
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error("사내 카페 댓글 조회 실패 [게시글 ID: %s]: %s", post_id, e)
            return []

    def create_cafe_comment(self, post_id: int, username: str, content: str) -> Optional[dict]:
        """특정 게시글에 댓글을 추가합니다."""
        conn = self._ensure_connection()
        try:
            if self.is_postgres:
                cursor = conn.execute(
                    """
                    INSERT INTO company_cafe_comments (post_id, username, content)
                    VALUES (%s, %s, %s)
                    RETURNING id
                    """,
                    (post_id, username, content)
                )
                row_id = cursor.fetchone()
                new_id = row_id[0] if row_id else None
                conn.commit()
                if new_id is None:
                    return None
                cursor = conn.execute(
                    """
                    SELECT c.id, c.post_id, c.username, c.content, c.created_at, c.updated_at, u.email
                    FROM company_cafe_comments c
                    LEFT JOIN users u ON c.username = u.username
                    WHERE c.id = %s
                    """,
                    (new_id,)
                )
            else:
                cursor = conn.execute(
                    """
                    INSERT INTO company_cafe_comments (post_id, username, content)
                    VALUES (?, ?, ?)
                    """,
                    (post_id, username, content)
                )
                new_id = cursor.lastrowid
                conn.commit()
                cursor = conn.execute(
                    """
                    SELECT c.id, c.post_id, c.username, c.content, c.created_at, c.updated_at, u.email
                    FROM company_cafe_comments c
                    LEFT JOIN users u ON c.username = u.username
                    WHERE c.id = ?
                    """,
                    (new_id,)
                )
            row = cursor.fetchone()
            return dict(row) if row else None
        except Exception as e:
            conn.rollback()
            logger.error("사내 카페 댓글 등록 실패 [게시글 ID: %s, 유저: %s]: %s", post_id, username, e)
            return None

    def delete_cafe_comment(self, comment_id: int, username: str, is_admin: bool = False) -> bool:
        """댓글을 삭제합니다."""
        conn = self._ensure_connection()
        try:
            if is_admin:
                cursor = conn.execute(
                    "DELETE FROM company_cafe_comments WHERE id = ?",
                    (comment_id,)
                )
            else:
                cursor = conn.execute(
                    "DELETE FROM company_cafe_comments WHERE id = ? AND username = ?",
                    (comment_id, username)
                )
            conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            conn.rollback()
            logger.error("사내 카페 댓글 삭제 실패 [댓글 ID: %s, 유저: %s]: %s", comment_id, username, e)
            return False

    def send_collaboration_proposal(self, sender_biz_id: str, receiver_biz_id: str, bid_ntce_no: str, message: str) -> bool:
        """새로운 공동 수급/협업 제안을 발송(저장)합니다."""
        conn = self._ensure_connection()
        try:
            # bid_ntce_no가 bid_announcements에 존재하는지 사전 확인 (없으면 NULL로 저장)
            effective_bid_no = bid_ntce_no or None
            if effective_bid_no:
                try:
                    if self.is_postgres:
                        check_cursor = conn.execute(
                            "SELECT COUNT(*) FROM bid_announcements WHERE bid_ntce_no = %s",
                            (effective_bid_no,)
                        )
                    else:
                        check_cursor = conn.execute(
                            "SELECT COUNT(*) FROM bid_announcements WHERE bid_ntce_no = ?",
                            (effective_bid_no,)
                        )
                    row = check_cursor.fetchone()
                    bid_exists = row[0] > 0 if row else False
                    if not bid_exists:
                        logger.info(
                            "bid_ntce_no '%s'가 bid_announcements에 없음 — NULL로 대체하여 제안 등록합니다 (송신: %s, 수신: %s)",
                            effective_bid_no, sender_biz_id, receiver_biz_id
                        )
                        effective_bid_no = None
                except Exception:
                    effective_bid_no = None

            if self.is_postgres:
                conn.execute(
                    """
                    INSERT INTO collaboration_proposals (sender_biz_id, receiver_biz_id, bid_ntce_no, message)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (sender_biz_id, receiver_biz_id, effective_bid_no, message)
                )
            else:
                conn.execute("BEGIN TRANSACTION")
                conn.execute(
                    """
                    INSERT INTO collaboration_proposals (sender_biz_id, receiver_biz_id, bid_ntce_no, message)
                    VALUES (?, ?, ?, ?)
                    """,
                    (sender_biz_id, receiver_biz_id, effective_bid_no, message)
                )
            conn.commit()
            return True
        except Exception as e:
            conn.rollback()
            logger.error("협업 제안 등록 실패 (송신: %s, 수신: %s): %s", sender_biz_id, receiver_biz_id, e)
            return False

    def toggle_cafe_post_like(self, post_id: int, username: str) -> dict:
        """게시글의 좋아요 상태를 토글(추가/삭제)하고 최종 개수 및 활성화 여부를 반환합니다."""
        conn = self._ensure_connection()
        try:
            # 먼저 눌렀는지 확인
            cursor = conn.execute(
                "SELECT 1 FROM company_cafe_likes WHERE post_id = ? AND username = ?",
                (post_id, username)
            )
            liked = cursor.fetchone() is not None
            
            if liked:
                conn.execute(
                    "DELETE FROM company_cafe_likes WHERE post_id = ? AND username = ?",
                    (post_id, username)
                )
                user_liked = 0
            else:
                conn.execute(
                    "INSERT INTO company_cafe_likes (post_id, username) VALUES (?, ?)",
                    (post_id, username)
                )
                user_liked = 1
            conn.commit()
            
            # 최종 좋아요 개수 조회
            cursor = conn.execute(
                "SELECT COUNT(*) FROM company_cafe_likes WHERE post_id = ?",
                (post_id,)
            )
            count_row = cursor.fetchone()
            like_count = count_row[0] if count_row else 0
            
            return {
                "success": True,
                "like_count": like_count,
                "user_liked": user_liked
            }
        except Exception as e:
            conn.rollback()
            logger.error("사내 카페 좋아요 토글 실패 [게시글 ID: %s, 유저: %s]: %s", post_id, username, e)
            return {"success": False, "like_count": 0, "user_liked": 0}

    # ──────────────────────────────────────────
    # 지자체 정책 및 뉴스 데이터 (municipal_policies) CRUD
    # ──────────────────────────────────────────

    def save_municipal_policies(self, policies: list[dict]) -> int:
        """지자체 정책 데이터를 DB에 일괄 저장합니다. 기존에 존재하는 동일 region, title은 덮어씁니다."""
        conn = self._ensure_connection()
        inserted = 0
        try:
            with conn:
                for p in policies:
                    keywords_json = json.dumps(p.get("keywords", []), ensure_ascii=False)
                    metadata_json = json.dumps(p.get("metadata", {}), ensure_ascii=False)
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO municipal_policies 
                        (region, title, category, department, budget, content, keywords, ai_summary, relevance_score, collected_at, metadata)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            p["region"],
                            p["title"],
                            p.get("category"),
                            p.get("department"),
                            p.get("budget", 0),
                            p.get("content", ""),
                            keywords_json,
                            p.get("ai_summary", ""),
                            p.get("relevance_score", 0.0),
                            p.get("collected_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
                            metadata_json
                        )
                    )
                    inserted += 1
            return inserted
        except Exception as e:
            logger.error("지자체 정책 저장 실패: %s", e)
            return 0

    def get_municipal_policies(self, region: str = None, category: str = None, search: str = None, limit: int = 50, offset: int = 0) -> list[dict]:
        """조건별 지자체 정책 목록을 조회합니다."""
        conn = self._ensure_connection()
        query = "SELECT * FROM municipal_policies WHERE 1=1"
        params = []
        
        if region:
            query += " AND region = ?"
            params.append(region)
        if category:
            query += " AND category = ?"
            params.append(category)
        if search:
            query += " AND (title LIKE ? OR content LIKE ?)"
            params.append(f"%{search}%")
            params.append(f"%{search}%")
            
        query += " ORDER BY relevance_score DESC, budget DESC, id DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        
        try:
            cursor = conn.execute(query, params)
            results = []
            for row in cursor.fetchall():
                item = dict(row)
                try:
                    item["keywords"] = json.loads(item["keywords"]) if item.get("keywords") else []
                except Exception:
                    item["keywords"] = []
                try:
                    item["metadata"] = json.loads(item["metadata"]) if item.get("metadata") else {}
                except Exception:
                    item["metadata"] = {}
                results.append(item)
            return results
        except Exception as e:
            logger.error("지자체 정책 조회 실패: %s", e)
            return []

    def get_municipal_policies_stats(self) -> list[dict]:
        """지자체(지역)별 정책 통계를 계산하여 조회합니다."""
        conn = self._ensure_connection()
        try:
            cursor = conn.execute(
                """
                SELECT 
                    region, 
                    COUNT(*) as count, 
                    SUM(budget) as total_budget, 
                    AVG(relevance_score) as avg_relevance
                FROM municipal_policies 
                GROUP BY region
                ORDER BY count DESC
                """
            )
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error("지자체 정책 통계 조회 실패: %s", e)
            return []

    def delete_all_municipal_policies(self) -> bool:
        """기존 수집된 모든 지자체 정책 데이터를 삭제합니다."""
        conn = self._ensure_connection()
        try:
            conn.execute("DELETE FROM municipal_policies")
            conn.commit()
            return True
        except Exception as e:
            conn.rollback()
            logger.error("지자체 정책 전체 삭제 실패: %s", e)
            return False

    def update_municipal_policy_nlp(self, policy_id: int, keywords: list[str], ai_summary: str, relevance_score: float) -> bool:
        """개별 정책의 NLP 분석 결과(키워드, 요약, 연관점수)를 업데이트합니다."""
        conn = self._ensure_connection()
        try:
            keywords_json = json.dumps(keywords, ensure_ascii=False)
            conn.execute(
                """
                UPDATE municipal_policies 
                SET keywords = ?, ai_summary = ?, relevance_score = ?
                WHERE id = ?
                """,
                (keywords_json, ai_summary, relevance_score, policy_id)
            )
            conn.commit()
            return True
        except Exception as e:
            conn.rollback()
            logger.error("지자체 정책 NLP 업데이트 실패 [ID: %s]: %s", policy_id, e)
            return False

    def get_proposals(self, category: Optional[str] = None, keyword: Optional[str] = None) -> list[dict]:
        """등록된 제안서 및 기획서 목록을 조회합니다."""
        conn = self._ensure_connection()
        query = "SELECT id, username, title, category, content, file_url, downloads, created_at, updated_at FROM proposal_shares WHERE 1=1"
        params = []
        
        if category and category.lower() != 'all':
            query += " AND category = ?"
            params.append(category)
            
        if keyword:
            query += " AND (title LIKE ? OR content LIKE ?)"
            params.append(f"%{keyword}%")
            params.append(f"%{keyword}%")
            
        query += " ORDER BY created_at DESC"
        
        try:
            cursor = conn.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error("제안서 목록 조회 실패: %s", e)
            return []

    def add_proposal(self, username: str, title: str, category: str, content: str, file_url: Optional[str] = None) -> None:
        """새로운 제안서/기획서 공유 글을 등록합니다."""
        conn = self._ensure_connection()
        try:
            conn.execute("BEGIN TRANSACTION")
            conn.execute(
                """
                INSERT INTO proposal_shares (username, title, category, content, file_url, downloads)
                VALUES (?, ?, ?, ?, ?, 0)
                """,
                (username, title, category, content, file_url)
            )
            conn.commit()
            logger.info("제안서 등록 성공 [유저: %s]: %s", username, title)
        except Exception as e:
            conn.rollback()
            logger.error("제안서 등록 실패: %s", e)
            raise

    def delete_proposal(self, proposal_id: int) -> bool:
        """제안서/기획서 공유 글을 삭제합니다."""
        conn = self._ensure_connection()
        try:
            conn.execute("BEGIN TRANSACTION")
            cursor = conn.execute("DELETE FROM proposal_shares WHERE id = ?", (proposal_id,))
            conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            conn.rollback()
            logger.error("제안서 삭제 실패 [ID: %s]: %s", proposal_id, e)
            return False

    def increment_proposal_downloads(self, proposal_id: int) -> None:
        """제안서/기획서 다운로드(조회) 수를 1 증가시킵니다."""
        conn = self._ensure_connection()
        try:
            conn.execute("BEGIN TRANSACTION")
            conn.execute(
                "UPDATE proposal_shares SET downloads = downloads + 1 WHERE id = ?",
                (proposal_id,)
            )
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error("제안서 다운로드 수 증가 실패 [ID: %s]: %s", proposal_id, e)

    def get_shared_businesses(self) -> list[BusinessProfile]:
        """정보 공유에 동의한(is_shared = 1) 모든 사업자 프로필 목록을 조회합니다."""
        conn = self._ensure_connection()
        try:
            cursor = conn.execute(
                "SELECT * FROM business_profiles WHERE is_shared = 1 ORDER BY company_name ASC"
            )
            profiles = []
            for row in cursor.fetchall():
                d = dict(row)
                d["username"] = "shared"  # 타사 정보이므로 username은 shared로 표시
                profiles.append(BusinessProfile.from_dict(d))
            return profiles
        except Exception as e:
            logger.error("공유 사업자 프로필 목록 조회 실패: %s", e)
            return []


    def get_received_proposals(self, biz_id: str) -> list[dict]:
        """특정 사업자 프로필이 수신한 협업 제안 목록을 조회합니다."""
        conn = self._ensure_connection()
        try:
            cursor = conn.execute(
                """
                SELECT cp.*, 
                       sp.company_name as sender_company_name,
                       sp.ceo_name as sender_ceo_name,
                       u.email as sender_email,
                       b.title as bid_title
                FROM collaboration_proposals cp
                JOIN business_profiles sp ON cp.sender_biz_id = sp.biz_id
                -- 제안 수락 시 연락망 제공을 위해 송신 회사 소유자의 이메일 연결
                LEFT JOIN business_members bm ON sp.biz_id = bm.biz_id AND bm.role = 'owner'
                LEFT JOIN users u ON bm.username = u.username
                LEFT JOIN bid_announcements b ON cp.bid_ntce_no = b.bid_ntce_no
                WHERE cp.receiver_biz_id = ?
                ORDER BY cp.created_at DESC
                """,
                (biz_id,)
            )
            rows = cursor.fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.error("수신 협업 제안 조회 실패 (biz_id: %s): %s", biz_id, e)
            return []

    def get_sent_proposals(self, biz_id: str) -> list[dict]:
        """특정 사업자 프로필이 발송한 협업 제안 목록을 조회합니다."""
        conn = self._ensure_connection()
        try:
            cursor = conn.execute(
                """
                SELECT cp.*, 
                       rp.company_name as receiver_company_name,
                       rp.ceo_name as receiver_ceo_name,
                       u.email as receiver_email,
                       b.title as bid_title
                FROM collaboration_proposals cp
                JOIN business_profiles rp ON cp.receiver_biz_id = rp.biz_id
                -- 제안 수락 시 연락망 제공을 위해 수신 회사 소유자의 이메일 연결
                LEFT JOIN business_members bm ON rp.biz_id = bm.biz_id AND bm.role = 'owner'
                LEFT JOIN users u ON bm.username = u.username
                LEFT JOIN bid_announcements b ON cp.bid_ntce_no = b.bid_ntce_no
                WHERE cp.sender_biz_id = ?
                ORDER BY cp.created_at DESC
                """,
                (biz_id,)
            )
            rows = cursor.fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.error("송신 협업 제안 조회 실패 (biz_id: %s): %s", biz_id, e)
            return []

    def update_proposal_status(self, proposal_id: int, status: str) -> bool:
        """협업 제안의 상태(pending, accepted, rejected)를 업데이트합니다."""
        conn = self._ensure_connection()
        try:
            conn.execute("BEGIN TRANSACTION")
            cursor = conn.execute(
                "UPDATE collaboration_proposals SET status = ?, updated_at = ? WHERE id = ?",
                (status, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), proposal_id)
            )
            conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            conn.rollback()
            logger.error("협업 제안 상태 수정 실패 (id: %s): %s", proposal_id, e)
            return False
