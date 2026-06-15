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
        sample_business_profile_dict["credit_rating"] = "AA"
        sample_business_profile_dict["company_type"] = "중견기업"
        sample_business_profile_dict["has_sanctions"] = True

        profile = BusinessProfile.from_dict(sample_business_profile_dict)
        db_manager.add_business(profile)

        businesses = db_manager.get_businesses()
        assert len(businesses) >= 1
        assert businesses[0].company_name == "테스트 IT솔루션"
        assert businesses[0].credit_rating == "AA"
        assert businesses[0].company_type == "중견기업"
        assert businesses[0].has_sanctions is True

    def test_update_business(self, db_manager, sample_business_profile_dict):
        """사업자 정보 업데이트"""
        profile = BusinessProfile.from_dict(sample_business_profile_dict)
        db_manager.add_business(profile)

        # 같은 biz_id로 업데이트
        profile.company_name = "수정된 회사명"
        profile.credit_rating = "A+"
        profile.company_type = "대기업"
        profile.has_sanctions = False
        db_manager.add_business(profile)

        businesses = db_manager.get_businesses()
        # UPSERT로 인해 기존 데이터가 업데이트되었는지 확인
        names = [b.company_name for b in businesses]
        assert "수정된 회사명" in names
        
        updated_profile = next(b for b in businesses if b.biz_id == profile.biz_id)
        assert updated_profile.credit_rating == "A+"
        assert updated_profile.company_type == "대기업"
        assert updated_profile.has_sanctions is False


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


class TestUserAndFavoriteCRUD:
    """회원 및 관심공고 CRUD + 사용자 격리 테스트"""

    def test_user_crud(self, db_manager):
        """회원 등록 및 조회 테스트"""
        db_manager.add_user("testuser1", "hashedpassword123", "test@nara.com")
        user = db_manager.get_user("testuser1")
        assert user is not None
        assert user["username"] == "testuser1"
        assert user["password_hash"] == "hashedpassword123"
        assert user["email"] == "test@nara.com"

        # 없는 유저 조회 시 None 반환
        assert db_manager.get_user("nonexistent") is None

    def test_favorite_crud(self, db_manager, sample_bid_dict):
        """관심공고 CRUD 테스트"""
        # 부모 테이블 제약조건 충족을 위한 유저 및 공고 저장
        db_manager.add_user("favuser", "hash")
        bid = BidAnnouncement.from_dict(sample_bid_dict)
        db_manager.save_bids([bid])

        # 추가
        db_manager.add_favorite("favuser", bid.bid_ntce_no, "reviewing", "메모내용")
        
        # 목록 조회
        favs = db_manager.get_favorites("favuser")
        assert len(favs) == 1
        assert favs[0]["bid_ntce_no"] == bid.bid_ntce_no
        assert favs[0]["memo"] == "메모내용"
        assert favs[0]["title"] == bid.title # JOIN 확인

        # 단일 조회
        fav = db_manager.get_favorite("favuser", bid.bid_ntce_no)
        assert fav is not None
        assert fav["memo"] == "메모내용"

        # 업데이트
        db_manager.update_favorite("favuser", bid.bid_ntce_no, status="proceeding", memo="메모수정")
        updated = db_manager.get_favorite("favuser", bid.bid_ntce_no)
        assert updated["status"] == "proceeding"
        assert updated["memo"] == "메모수정"

        # 삭제
        success = db_manager.delete_favorite("favuser", bid.bid_ntce_no)
        assert success is True
        assert db_manager.get_favorite("favuser", bid.bid_ntce_no) is None

    def test_multi_user_isolation(self, db_manager, sample_bid_dict):
        """다중 사용자 격리 테스트 (관심공고 및 사업자 프로필)"""
        # 유저 1, 2 등록
        db_manager.add_user("user1", "hash")
        db_manager.add_user("user2", "hash")
        
        # 공고 1, 2 등록
        bid1 = BidAnnouncement(bid_ntce_no="BID111", title="공고1")
        bid2 = BidAnnouncement(bid_ntce_no="BID222", title="공고2")
        db_manager.save_bids([bid1, bid2])

        # user1 -> bid1 관심공고 등록
        db_manager.add_favorite("user1", "BID111", "reviewing", "user1메모")
        # user2 -> bid2 관심공고 등록
        db_manager.add_favorite("user2", "BID222", "reviewing", "user2메모")

        # 관심공고 격리 조회 검증
        favs1 = db_manager.get_favorites("user1")
        assert len(favs1) == 1
        assert favs1[0]["bid_ntce_no"] == "BID111"

        favs2 = db_manager.get_favorites("user2")
        assert len(favs2) == 1
        assert favs2[0]["bid_ntce_no"] == "BID222"

        # 사업자 프로필 격리 검증 (다른 biz_id를 각 유저가 소유 등록)
        profile1 = BusinessProfile(biz_id="111-22-33333", company_name="회사A", username="user1")
        profile2 = BusinessProfile(biz_id="444-55-66666", company_name="회사B", username="user2")
        
        db_manager.add_business(profile1)
        db_manager.add_business(profile2)

        # 각자 조회했을 때 자신 소유의 프로필만 뜨는지 검증
        biz1 = db_manager.get_business("111-22-33333", "user1")
        assert biz1 is not None
        assert biz1.company_name == "회사A"

        # 타 유저가 조회 시 권한 격리로 조회 불가능 (None)
        biz1_for_user2 = db_manager.get_business("111-22-33333", "user2")
        assert biz1_for_user2 is None

        biz2 = db_manager.get_business("444-55-66666", "user2")
        assert biz2 is not None
        assert biz2.company_name == "회사B"

        biz2_for_user1 = db_manager.get_business("444-55-66666", "user1")
        assert biz2_for_user1 is None
        
        # 전체 조회 격리 검증
        list1 = db_manager.get_businesses("user1")
        assert len(list1) == 1
        assert list1[0].company_name == "회사A"

        list2 = db_manager.get_businesses("user2")
        assert len(list2) == 1
        assert list2[0].company_name == "회사B"


class TestCompetitorMarketShare:
    """경쟁사 수주 점유율 분석 테스트"""

    def test_get_competitor_market_share(self, db_manager):
        # 1. 테스트용 부모 입찰 공고들 저장
        bids = [
            BidAnnouncement(bid_ntce_no="BID-COMP-001", title="시스템 구축 1"),
            BidAnnouncement(bid_ntce_no="BID-COMP-002", title="시스템 구축 2"),
            BidAnnouncement(bid_ntce_no="BID-COMP-003", title="시스템 구축 3"),
            BidAnnouncement(bid_ntce_no="BID-COMP-004", title="시스템 구축 4"),
        ]
        db_manager.save_bids(bids)

        # 2. 테스트용 낙찰 정보 저장
        # winner_name과 award_amount, bid_rate 설정
        awards = [
            AwardInfo(
                bid_ntce_no="BID-COMP-001",
                winner_name="경쟁사A",
                award_amount=100000000, # 1억
                bid_rate=87.5,
            ),
            AwardInfo(
                bid_ntce_no="BID-COMP-002",
                winner_name="경쟁사A",
                award_amount=200000000, # 2억
                bid_rate=88.5,
            ),
            AwardInfo(
                bid_ntce_no="BID-COMP-003",
                winner_name="경쟁사B",
                award_amount=150000000, # 1.5억
                bid_rate=86.0,
            ),
            AwardInfo(
                bid_ntce_no="BID-COMP-004",
                winner_name="경쟁사C",
                award_amount=50000000,  # 0.5억
                bid_rate=90.0,
            ),
        ]
        db_manager.save_awards(awards)

        # 3. 경쟁사 점유율 분석 메서드 호출
        stats = db_manager.get_competitor_market_share(limit=2)

        # limit 작동 확인
        assert len(stats) == 2

        # 랭킹 확인 (A가 2건으로 1위, B가 1건/1.5억으로 2위, C는 1건/0.5억으로 3위이나 limit=2이므로 미포함)
        assert stats[0]["winner_name"] == "경쟁사A"
        assert stats[0]["win_count"] == 2
        assert stats[0]["total_award_amount"] == 300000000
        assert stats[0]["avg_bid_rate"] == 88.0  # (87.5 + 88.5) / 2 = 88.0

        assert stats[1]["winner_name"] == "경쟁사B"
        assert stats[1]["win_count"] == 1
        assert stats[1]["total_award_amount"] == 150000000
        assert stats[1]["avg_bid_rate"] == 86.0
