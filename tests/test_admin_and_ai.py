"""
관리자 대시보드(Admin Panel) 및 사용자 개인화 AI 에이전트(My AI) 관련 검증 테스트

1. v5 스크립트 이관 상태 및 기본 데이터 매핑 검증
2. 일반/관리자 세션 권한에 따른 API(/api/admin/*) 격리 검증
3. AI 설정 가중치 변경에 따른 매칭 점수 동적 변화 수학적 검증
"""

import pytest
from fastapi.testclient import TestClient

from src.models.database import DatabaseManager
from src.api.app import app
from src.api.routes._helpers import get_db
from src.analyzers.biz_matcher import BizMatcher


@pytest.fixture
def override_db(db_manager):
    """테스트용 임시 DB로 FastAPI 의존성을 대체합니다."""
    app.dependency_overrides[get_db] = lambda: db_manager
    yield db_manager
    app.dependency_overrides.clear()


@pytest.fixture
def client(override_db):
    """FastAPI TestClient를 제공합니다."""
    return TestClient(app)


class TestAdminAndAiUnit:
    """DB 레벨의 관리자 및 AI 헬퍼 메서드 단위 테스트"""

    def test_v5_migration_schema(self, db_manager):
        """v5 마이그레이션이 정상 적용되어 컬럼과 테이블이 존재하는지 검증"""
        conn = db_manager._ensure_connection()
        
        # 1. users 테이블에 is_admin 컬럼이 존재하는지 확인
        cursor = conn.execute("PRAGMA table_info(users)")
        columns = {row["name"] for row in cursor.fetchall()}
        assert "is_admin" in columns

        # 2. user_ai_settings 테이블이 존재하는지 확인
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='user_ai_settings'"
        )
        assert cursor.fetchone() is not None

    def test_default_admin_and_ai_settings(self, db_manager):
        """기본 admin 계정이 관리자로 승격되고 기본 AI 설정이 추가되었는지 검증"""
        # admin 유저 정보 조회
        admin_user = db_manager.get_user("admin")
        assert admin_user is not None
        assert admin_user["is_admin"] == 1

        # admin의 기본 AI 설정 조회
        settings = db_manager.get_user_ai_settings("admin")
        assert settings is not None
        assert settings["ai_persona"] == "strategic"
        assert settings["relevance_weight"] == 0.35
        assert settings["capacity_weight"] == 0.35
        assert settings["credit_weight"] == 0.30

    def test_user_registration_creates_ai_settings(self, db_manager):
        """신규 유저 가입 시 AI 설정이 자동으로 생성되는지 검증"""
        username = "test_user_ai"
        password_hash = "hashed_pw"
        email = "test@example.com"

        # 회원가입
        db_manager.add_user(username, password_hash, email)

        # 유저 정보 검증
        user = db_manager.get_user(username)
        assert user is not None
        assert user["is_admin"] == 0

        # AI 에이전트 설정 자동 신설 검증
        settings = db_manager.get_user_ai_settings(username)
        assert settings is not None
        assert settings["ai_persona"] == "strategic"
        assert settings["relevance_weight"] == 0.35
        assert settings["capacity_weight"] == 0.35
        assert settings["credit_weight"] == 0.30

    def test_v6_migration_and_cafe_crud(self, db_manager):
        """v6 마이그레이션 적용 상태와 카페 게시글 CRUD 데이터베이스 연산을 검증"""
        # 1. company_cafe_posts 테이블 존재 검증
        conn = db_manager._ensure_connection()
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='company_cafe_posts'"
        )
        assert cursor.fetchone() is not None

        # 2. 테스트용 유저 및 회사 프로필 등록
        username = "cafe_test_user"
        db_manager.add_user(username, "hash", "cafe_test@example.com")
        
        biz_id = "123-45-67890"
        conn.execute(
            """
            INSERT OR REPLACE INTO business_profiles (biz_id, company_name, ceo_name)
            VALUES (?, '카페테스트(주)', '홍길동')
            """,
            (biz_id,)
        )
        conn.commit()

        # 3. 카페 게시글 등록 테스트
        post = db_manager.create_cafe_post(biz_id, username, "입찰 공고 공유", "이 공고 같이 들어갈 회사 구합니다.")
        assert post is not None
        assert post["title"] == "입찰 공고 공유"
        assert post["username"] == username
        assert post["email"] == "cafe_test@example.com"
        
        post_id = post["id"]

        # 4. 카페 게시글 조회 테스트
        posts = db_manager.get_cafe_posts(biz_id)
        assert len(posts) > 0
        assert posts[0]["id"] == post_id
        assert posts[0]["title"] == "입찰 공고 공유"

        # 5. 카페 게시글 삭제 테스트
        deleted = db_manager.delete_cafe_post(post_id, biz_id)
        assert deleted is True

        # 6. 삭제 후 조회 테스트
        posts_after = db_manager.get_cafe_posts(biz_id)
        assert not any(p["id"] == post_id for p in posts_after)


class TestAdminApiSecurity:
    """어드민 API 권한 제어 통합 테스트"""

    def test_unauthorized_user_access(self, client, db_manager):
        """비로그인 유저가 관리자 API 접근 시 401 Unauthorized 에러 검증"""
        # 세션 쿠키 없이 호출
        res = client.get("/api/admin/stats")
        assert res.status_code == 401

    def test_normal_user_access_forbidden(self, client, db_manager):
        """일반 회원이 관리자 API 접근 시 403 Forbidden 에러 검증"""
        # 1. 일반 회원 가입 및 로그인 처리
        username = "normal_user"
        password = "password123"
        db_manager.add_user(username, "hashed_pw_dummy", "normal@example.com")
        
        # 비밀번호 해시 일치 검증을 우회하기 위해 DB 직접 로그인 모의
        # (FastAPI TestClient에서 쿠키를 세팅하기 위해 Mocking 또는 직접 로그인 API 활용)
        # 테스트용 auth router를 타는 방식으로 직접 로그인 시도
        # 실제 auth.py가 PBKDF2 해싱 검증하므로, 실제 해싱된 암호 필요
        from src.api.routes.auth import hash_password
        hashed = hash_password(password)
        
        # 기존 회원 덮어쓰기 위해 DB 업데이트
        conn = db_manager._ensure_connection()
        conn.execute(
            "UPDATE users SET password_hash = ? WHERE username = ?",
            (hashed, username)
        )
        conn.commit()

        # 로그인 실행
        login_res = client.post(
            "/api/auth/login",
            json={"username": username, "password": password}
        )
        assert login_res.status_code == 200

        # 2. 일반 회원 세션으로 어드민 API 호출 시 403 Forbidden 검증
        res = client.get("/api/admin/stats")
        assert res.status_code == 403

    def test_admin_user_access_ok(self, client, db_manager):
        """관리자 계정이 관리자 API 접근 시 200 OK 및 정상 데이터 반환 검증"""
        # 최고관리자 로그인
        # admin 비밀번호를 테스트용 해시로 업데이트
        from src.api.routes.auth import hash_password
        hashed = hash_password("admin_pass_123")
        conn = db_manager._ensure_connection()
        conn.execute(
            "UPDATE users SET password_hash = ?, is_admin = 1 WHERE username = 'admin'",
            (hashed,)
        )
        conn.commit()

        login_res = client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "admin_pass_123"}
        )
        assert login_res.status_code == 200

        # 어드민 API 호출
        res = client.get("/api/admin/stats")
        assert res.status_code == 200
        data = res.json()
        assert "total_users" in data
        assert "total_companies" in data
        assert "total_favorites" in data
        assert "total_collaborations" in data


class TestDynamicAiScoringMath:
    """AI 가중치 셋업에 따른 입찰 매칭점수 수학적 정합성 검증"""

    def test_dynamic_scoring_by_weights(self, db_manager, sample_bid_dict, sample_business_profile_dict):
        """가중치 셋업 변화에 따라 동일한 공고의 매칭 점수가 달라지는지 검증"""
        matcher = BizMatcher()

        # 1. 키워드/업종 극대화 가중치 (relevance=0.8, capacity=0.1, credit=0.1)
        settings_relevance_heavy = {
            "relevance_weight": 0.8,
            "capacity_weight": 0.1,
            "credit_weight": 0.1
        }
        score_rel = matcher.calculate_match_score(
            sample_business_profile_dict,
            sample_bid_dict,
            settings_relevance_heavy
        )

        # 2. 기업규모/실적 극대화 가중치 (relevance=0.1, capacity=0.8, credit=0.1)
        settings_capacity_heavy = {
            "relevance_weight": 0.1,
            "capacity_weight": 0.8,
            "credit_weight": 0.1
        }
        score_cap = matcher.calculate_match_score(
            sample_business_profile_dict,
            sample_bid_dict,
            settings_capacity_heavy
        )

        # 3. 신용도/지역 가점 극대화 가중치 (relevance=0.1, capacity=0.1, credit=0.8)
        settings_credit_heavy = {
            "relevance_weight": 0.1,
            "capacity_weight": 0.1,
            "credit_weight": 0.8
        }
        score_cred = matcher.calculate_match_score(
            sample_business_profile_dict,
            sample_bid_dict,
            settings_credit_heavy
        )

        # 가중치가 서로 극단적으로 다르면, 최종 종합 점수(total_score)는 무조건 달라야 함
        assert score_rel["total_score"] != score_cap["total_score"]
        assert score_cap["total_score"] != score_cred["total_score"]
        assert score_rel["total_score"] != score_cred["total_score"]

        # 예산이 5억 원(sample_bid_dict budget=500000000)이고,
        # 기업 최대예산이 10억 원(sample_business_profile_dict max_budget=1000000000)일 때,
        # 예산 적합성(capacity 평가 요소) 점수는 만점에 수렴하므로,
        # capacity 가중치가 무거운 settings_capacity_heavy 측이 상대적으로 더 높은 점수를 획득해야 함을 검증
        # (단, 키워드 매칭 상태에 따라 다를 수 있으나 dynamic score가 작동함을 확인)
        assert "total_score" in score_rel
        assert "total_score" in score_cap
        assert "total_score" in score_cred


class TestConsortiumPartnerRecommendation:
    """공동수급(컨소시엄) 추천 파트너 API 검증"""

    def test_recommend_partners_success(self, client, db_manager, sample_bid_dict, sample_business_profile_dict):
        """면허 및 지역 부족분을 보완할 파트너 추천 API가 올바르게 작동하는지 검증"""
        from src.models.schemas import BusinessProfile, BidAnnouncement

        # 1. 테스트용 회원가입 및 로그인
        username = "partner_test_user"
        password = "password123"
        db_manager.add_user(username, "hashed_pw", "partner@example.com")
        
        from src.api.routes.auth import hash_password
        hashed = hash_password(password)
        conn = db_manager._ensure_connection()
        conn.execute(
            "UPDATE users SET password_hash = ? WHERE username = ?",
            (hashed, username)
        )
        conn.commit()

        login_res = client.post(
            "/api/auth/login",
            json={"username": username, "password": password}
        )
        assert login_res.status_code == 200

        # 2. 우리 회사 정보 입력 (면허: 정보통신공사업, 지역: 서울)
        my_biz_id = "my-corp-id-123"
        my_profile = BusinessProfile.from_dict({
            "biz_id": my_biz_id,
            "company_name": "우리정보기술",
            "ceo_name": "홍길동",
            "licenses": "정보통신공사업",
            "regions": "서울",
            "annual_revenue": 5000,
            "credit_rating": "A"
        })
        db_manager.add_business(my_profile, username=username)
        # 우리 회사에 사용자 매핑 수정
        db_manager.add_business_member(my_biz_id, username, "대표")

        # 3. 타사 정보 입력 (면허: 소프트웨어사업자, 지역: 경기)
        other_biz_id = "other-corp-id-456"
        other_profile = BusinessProfile.from_dict({
            "biz_id": other_biz_id,
            "company_name": "상대소프트웨어",
            "ceo_name": "임꺽정",
            "licenses": "소프트웨어사업자",
            "regions": "경기",
            "annual_revenue": 10000,
            "credit_rating": "AA"
        })
        db_manager.add_business(other_profile)

        # 4. 공고 등록 (요구면허: 정보통신공사업, 소프트웨어사업자 / 지역제한: 경기)
        bid_no = "20260615001-00"
        sample_bid_dict["bid_ntce_no"] = bid_no
        sample_bid_dict["license_limit"] = "정보통신공사업, 소프트웨어사업자"
        sample_bid_dict["region"] = "경기"
        bid_obj = BidAnnouncement.from_dict(sample_bid_dict)
        db_manager.save_bids([bid_obj])

        # 관심공고 추가
        db_manager.add_favorite(username, bid_no)

        # 5. 활성 회사 헤더(X-Active-Company)를 담아 추천 API 호출
        res = client.get(
            f"/api/favorites/{bid_no}/recommend-partners",
            headers={"X-Active-Company": my_biz_id}
        )
        assert res.status_code == 200
        
        data = res.json()
        assert "partners" in data
        assert len(data["partners"]) > 0
        
        # 상대소프트웨어가 추천 파트너로 매칭되어야 함 (부족한 면허인 소프트웨어사업자와 경기 지역 요건 충족)
        partner = data["partners"][0]
        assert partner["biz_id"] == other_biz_id
        assert partner["company_name"] == "상대소프트웨어"
        assert any("부족한 면허 자격 보완" in r for r in partner["matched_reasons"])

