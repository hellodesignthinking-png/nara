"""
DatabaseManager CRUD 테스트

임시 SQLite DB를 사용하여 CRUD 연산, UPSERT, 마이그레이션 등을 검증합니다.
"""

import pytest

from src.models.database import DatabaseManager
from src.models.schemas import (
    BidAnnouncement,
    AwardInfo,
    NewsArticle,
    AnalysisResult,
    BusinessProfile,
)


class TestDatabaseInit:
    """DB 초기화 및 마이그레이션 테스트"""

    def test_init_creates_tables(self, db_manager):
        """init_db()가 모든 테이블을 생성하는지 확인"""
        conn = db_manager._ensure_connection()
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = {row[0] for row in cursor.fetchall()}

        expected = {
            "bid_announcements",
            "award_infos",
            "news_articles",
            "analysis_results",
            "business_profiles",
            "schema_version",
        }
        assert expected.issubset(tables)

    def test_schema_version_set(self, db_manager):
        """마이그레이션 후 스키마 버전이 기록되는지 확인"""
        conn = db_manager._ensure_connection()
        cursor = conn.execute("SELECT MAX(version) FROM schema_version")
        version = cursor.fetchone()[0]
        assert version == db_manager.CURRENT_SCHEMA_VERSION

    def test_idempotent_init(self, db_manager):
        """init_db()를 여러 번 호출해도 안전한지 확인"""
        db_manager.init_db()  # 두 번째 호출
        db_manager.init_db()  # 세 번째 호출

        conn = db_manager._ensure_connection()
        cursor = conn.execute("SELECT COUNT(*) FROM schema_version")
        count = cursor.fetchone()[0]
        assert count >= 1


class TestBidCRUD:
    """입찰공고 CRUD 테스트"""

    def test_save_and_get_bids(self, db_manager, sample_bid_dict):
        bid = BidAnnouncement.from_dict(sample_bid_dict)
        saved = db_manager.save_bids([bid])
        assert saved == 1

        bids = db_manager.search_bids("AI")
        assert len(bids) >= 1

    def test_save_duplicate_ignored(self, db_manager, sample_bid_dict):
        """동일한 공고를 두 번 저장하면 중복 무시"""
        bid = BidAnnouncement.from_dict(sample_bid_dict)
        db_manager.save_bids([bid])
        saved = db_manager.save_bids([bid])
        assert saved == 0

    def test_save_multiple_bids(self, db_manager):
        """여러 공고를 한 번에 저장 (executemany 테스트)"""
        bids = []
        for i in range(10):
            bids.append(BidAnnouncement(
                bid_ntce_no=f"BATCH{i:04d}",
                title=f"테스트 공고 {i}",
                org_name="테스트 기관",
            ))
        saved = db_manager.save_bids(bids)
        assert saved == 10


class TestAwardCRUD:
    """낙찰정보 CRUD 테스트"""

    def test_save_and_get_awards(self, db_manager, sample_award_dict, sample_bid_dict):
        # FK 제약: 부모 bid 레코드 먼저 삽입
        parent_bid = BidAnnouncement.from_dict({**sample_bid_dict, "bid_ntce_no": sample_award_dict["bid_ntce_no"]})
        db_manager.save_bids([parent_bid])

        award = AwardInfo.from_dict(sample_award_dict)
        saved = db_manager.save_awards([award])
        assert saved == 1

    def test_save_duplicate_ignored(self, db_manager, sample_award_dict, sample_bid_dict):
        # FK 제약: 부모 bid 레코드 먼저 삽입
        parent_bid = BidAnnouncement.from_dict({**sample_bid_dict, "bid_ntce_no": sample_award_dict["bid_ntce_no"]})
        db_manager.save_bids([parent_bid])

        award = AwardInfo.from_dict(sample_award_dict)
        db_manager.save_awards([award])
        saved = db_manager.save_awards([award])
        assert saved == 0


class TestNewsCRUD:
    """뉴스기사 CRUD 테스트"""

    def test_save_and_get_news(self, db_manager, sample_news_dict):
        article = NewsArticle.from_dict(sample_news_dict)
        saved = db_manager.save_news([article])
        assert saved == 1

    def test_save_duplicate_ignored(self, db_manager, sample_news_dict):
        article = NewsArticle.from_dict(sample_news_dict)
        db_manager.save_news([article])
        saved = db_manager.save_news([article])
        assert saved == 0


class TestBusinessCRUD:
    """사업자 프로필 CRUD 테스트"""

    def test_add_and_get_business(self, db_manager, sample_business_profile_dict):
        profile = BusinessProfile.from_dict(sample_business_profile_dict)
        db_manager.add_business(profile)

        businesses = db_manager.get_businesses()
        assert len(businesses) >= 1
        assert businesses[0].company_name == "테스트 IT솔루션"

    def test_update_business(self, db_manager, sample_business_profile_dict):
        """사업자 정보 업데이트"""
        profile = BusinessProfile.from_dict(sample_business_profile_dict)
        db_manager.add_business(profile)

        # 같은 biz_id로 업데이트
        profile.company_name = "수정된 회사명"
        db_manager.add_business(profile)

        businesses = db_manager.get_businesses()
        # UPSERT로 인해 기존 데이터가 업데이트되었는지 확인
        names = [b.company_name for b in businesses]
        assert "수정된 회사명" in names


class TestAnalysisCRUD:
    """분석결과 CRUD 테스트"""

    def test_save_analysis(self, db_manager, sample_bid_dict):
        # 먼저 공고 저장
        bid = BidAnnouncement.from_dict(sample_bid_dict)
        db_manager.save_bids([bid])

        # 사업자 프로필 저장 (FK 제약)
        profile = BusinessProfile.from_dict({
            "biz_id": "1234567890",
            "company_name": "테스트 회사",
        })
        db_manager.add_business(profile)

        # 분석 결과 저장
        analysis = AnalysisResult(
            bid_ntce_no="20240101001",
            biz_id="1234567890",
            relevance_score=85.5,
            match_score=72.3,
            summary="테스트 분석 요약",
        )
        db_manager.save_analysis(analysis)

        # 분석 결과 조회
        results = db_manager.get_analyses_by_bid("20240101001")
        assert len(results) >= 1


class TestSearch:
    """검색 기능 테스트"""

    def test_search_bids_by_keyword(self, db_manager):
        """키워드 검색"""
        bids = [
            BidAnnouncement(bid_ntce_no="S001", title="AI 기반 시스템 구축"),
            BidAnnouncement(bid_ntce_no="S002", title="건물 유지보수 용역"),
            BidAnnouncement(bid_ntce_no="S003", title="빅데이터 분석 플랫폼"),
        ]
        db_manager.save_bids(bids)

        results = db_manager.search_bids("AI")
        assert any("AI" in b.title for b in results)

    def test_get_stats(self, db_manager, sample_bid_dict):
        """통계 조회"""
        bid = BidAnnouncement.from_dict(sample_bid_dict)
        db_manager.save_bids([bid])

        stats = db_manager.get_stats()
        assert isinstance(stats, dict)
        assert "bid_announcements" in stats
