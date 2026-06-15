"""
다중 회사 및 직원 관리(조직 관리) 통합/단위 테스트

v4 DB 마이그레이션 이관 검증, DB 헬퍼 계층 권한 제어,
그리고 API 레벨에서의 권한 격리를 검증합니다.
"""

import sqlite3
import pytest
from fastapi.testclient import TestClient

from src.models.database import DatabaseManager
from src.models.schemas import BusinessProfile
from src.api.app import app

# 테스트용 TestClient 구성
client = TestClient(app)


@pytest.fixture
def clean_db(tmp_db_path):
    """v3 스키마 단계까지만 수동으로 구축하고 데이터를 삽입할 수 있는 특수 픽스처"""
    db = DatabaseManager(tmp_db_path)
    return db


def test_v4_migration_data_transfer(clean_db):
    """
    v4 마이그레이션 적용 시, 기존 business_profiles 테이블에 있던
    (biz_id, username) 소유자 매핑 데이터가
    신설된 business_members 테이블로 정상적으로 role='owner'로 안전 이관되는지 검증합니다.
    """
    conn = clean_db._ensure_connection()
    
    # 1. 수동으로 v1~v3 스키마 형태를 가상 구축
    # 먼저 schema_version 테이블과 v3까지의 테이블 생성
    conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY, description TEXT, applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
    
    # v1 schema 중 business_profiles
    conn.execute("""
        CREATE TABLE IF NOT EXISTS business_profiles (
            biz_id TEXT PRIMARY KEY,
            company_name TEXT NOT NULL,
            ceo_name TEXT,
            business_types TEXT,
            licenses TEXT,
            regions TEXT,
            past_projects TEXT,
            annual_revenue INTEGER,
            employee_count INTEGER,
            keywords TEXT,
            min_budget INTEGER,
            max_budget INTEGER,
            credit_rating TEXT DEFAULT 'BBB',
            company_type TEXT,
            has_sanctions INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # v3 schema 변경 사항 (users 테이블 추가 및 business_profiles에 username 추가)
    conn.execute("CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password_hash TEXT NOT NULL, email TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
    conn.execute("ALTER TABLE business_profiles ADD COLUMN username TEXT REFERENCES users(username) DEFAULT 'admin'")
    
    # schema_version 기록을 3으로 설정
    conn.execute("INSERT OR REPLACE INTO schema_version (version, description) VALUES (3, 'v3 상태 수동 세팅')")
    
    # 2. 기존 데이터 삽입 (기존 비즈니스 프로필 및 유저)
    conn.execute("INSERT INTO users (username, password_hash, email) VALUES ('user1', 'hash1', 'user1@example.com')")
    conn.execute("INSERT INTO users (username, password_hash, email) VALUES ('user2', 'hash2', 'user2@example.com')")
    conn.execute("INSERT INTO users (username, password_hash, email) VALUES ('admin', 'default_placeholder', 'admin@nara-analyzer.local')")
    
    conn.execute("""
        INSERT INTO business_profiles (biz_id, company_name, ceo_name, username)
        VALUES ('111-11-11111', '회사1', '대표1', 'user1')
    """)
    conn.execute("""
        INSERT INTO business_profiles (biz_id, company_name, ceo_name, username)
        VALUES ('222-22-22222', '회사2', '대표2', 'user2')
    """)
    conn.commit()
    
    # 3. DatabaseManager.init_db() 실행하여 v4 마이그레이션 유도
    clean_db.init_db()
    
    # 4. 검증: business_profiles가 단독 PK로 재생성되었고 business_members에 데이터가 온전히 이관되었는가?
    cursor = conn.execute("SELECT * FROM business_members ORDER BY biz_id")
    members = [dict(row) for row in cursor.fetchall()]
    
    assert len(members) == 2
    
    # 회사1 검증 (owner는 user1)
    assert members[0]["biz_id"] == "111-11-11111"
    assert members[0]["username"] == "user1"
    assert members[0]["role"] == "owner"
    
    # 회사2 검증 (owner는 user2)
    assert members[1]["biz_id"] == "222-22-22222"
    assert members[1]["username"] == "user2"
    assert members[1]["role"] == "owner"


def test_db_manager_member_crud(db_manager):
    """DatabaseManager 내 조직/멤버 관리 헬퍼 메서드 기능 검증"""
    db = db_manager
    conn = db._ensure_connection()
    
    # 테스트 유저 추가
    conn.execute("INSERT OR IGNORE INTO users (username, password_hash, email) VALUES ('owner_user', 'hash', 'owner@example.com')")
    conn.execute("INSERT OR IGNORE INTO users (username, password_hash, email) VALUES ('employee_user', 'hash', 'emp@example.com')")
    conn.commit()
    
    # 1. 회사 생성 (add_business를 호출하면 내부적으로 owner로 등록되어야 함)
    profile = BusinessProfile(
        biz_id="999-99-99999",
        company_name="테스트 컴퍼니",
        ceo_name="대표자",
        business_types=[],
        licenses=[],
        regions=[],
        past_projects=[],
        annual_revenue=100,
        employee_count=10
    )
    db.add_business(profile, username="owner_user")
    
    # 권한 검증: owner_user 가 'owner' 역할을 갖고 있는가?
    role = db.get_business_user_role("999-99-99999", "owner_user")
    assert role == "owner"
    
    # 2. 직원 추가 (add_business_member)
    success = db.add_business_member("999-99-99999", "employee_user", "member")
    assert success is True
    
    # 직원 권한 조회
    role_emp = db.get_business_user_role("999-99-99999", "employee_user")
    assert role_emp == "member"
    
    # 3. 직원 목록 조회 (get_business_members)
    members = db.get_business_members("999-99-99999")
    usernames = [m["username"] for m in members]
    assert "owner_user" in usernames
    assert "employee_user" in usernames
    
    # 4. 직원 역할 수정 (update_business_member_role)
    update_success = db.update_business_member_role("999-99-99999", "employee_user", "admin")
    assert update_success is True
    assert db.get_business_user_role("999-99-99999", "employee_user") == "admin"
    
    # 5. 직원 삭제 / 퇴사 (remove_business_member)
    remove_success = db.remove_business_member("999-99-99999", "employee_user")
    assert remove_success is True
    assert db.get_business_user_role("999-99-99999", "employee_user") is None


def test_api_permission_isolation(db_manager):
    """
    API 레벨에서 활성 회사 권한을 체크하여 비인증 유저나 타사 직원의 
    수정/삭제/조회 접근 차단(403 Forbidden) 여부를 검증합니다.
    """
    db = db_manager
    conn = db._ensure_connection()
    
    # 유저 가입
    conn.execute("INSERT OR IGNORE INTO users (username, password_hash, email) VALUES ('alice', 'hash', 'alice@test.com')")
    conn.execute("INSERT OR IGNORE INTO users (username, password_hash, email) VALUES ('bob', 'hash', 'bob@test.com')")
    conn.commit()
    
    # alice 명의 회사 등록 (alice = owner)
    profile_alice = BusinessProfile(
        biz_id="111-22-33333",
        company_name="앨리스테크",
        ceo_name="앨리스"
    )
    db.add_business(profile_alice, username="alice")
    
    # bob 명의 회사 등록 (bob = owner)
    profile_bob = BusinessProfile(
        biz_id="444-55-66666",
        company_name="밥소프트",
        ceo_name="밥"
    )
    db.add_business(profile_bob, username="bob")

    # FASTAPI 의존성 오버라이드를 통한 인증 우회 및 DB 픽스처 삽입
    # app_state 및 DB 연결 싱글톤 처리를 위해 db_manager 주입 필요
    from src.api.routes._helpers import get_db, get_current_user
    
    app.dependency_overrides[get_db] = lambda: db
    
    # 1단계: bob 계정으로 인증 우회 상태에서 alice 회사에 권한 관련 행위를 시도해 봅니다.
    app.dependency_overrides[get_current_user] = lambda: "bob"
    
    # bob이 alice 회사에 직원을 추가하려고 할 때 -> 403 Forbidden 예상
    response = client.post(
        "/api/companies/111-22-33333/members",
        json={"username": "bob", "role": "member"}
    )
    assert response.status_code == 403
    
    # bob이 alice 회사의 프로필을 수정하려고 할 때 -> 403 Forbidden 예상
    response_update = client.put(
        "/api/businesses/111-22-33333",
        json={
            "biz_id": "111-22-33333",
            "company_name": "해킹된앨리스테크",
            "ceo_name": "앨리스",
            "business_types": [],
            "licenses": [],
            "regions": [],
            "past_projects": [],
            "annual_revenue": 0,
            "employee_count": 0
        }
    )
    assert response_update.status_code == 403
    
    # 2단계: alice 계정으로 인증 우회하여 alice 회사에 bob을 직원으로 추가
    app.dependency_overrides[get_current_user] = lambda: "alice"
    response_add = client.post(
        "/api/companies/111-22-33333/members",
        json={"username": "bob", "role": "member"}
    )
    assert response_add.status_code == 200
    
    # 3단계: bob으로 다시 전환하여 alice 회사에 소속된 상태로 프로필 수정을 시도함
    # bob은 member 등급이므로 수정 권한(owner/admin)이 없어야 함 -> 403 Forbidden
    app.dependency_overrides[get_current_user] = lambda: "bob"
    response_update_member = client.put(
        "/api/businesses/111-22-33333",
        json={
            "biz_id": "111-22-33333",
            "company_name": "수정시도앨리스테크",
            "ceo_name": "앨리스",
            "business_types": [],
            "licenses": [],
            "regions": [],
            "past_projects": [],
            "annual_revenue": 0,
            "employee_count": 0
        }
    )
    assert response_update_member.status_code == 403
    
    # 4단계: alice가 bob을 admin으로 격상시킴
    app.dependency_overrides[get_current_user] = lambda: "alice"
    response_role = client.put(
        "/api/companies/111-22-33333/members/bob",
        json={"role": "admin"}
    )
    assert response_role.status_code == 200
    
    # 5단계: bob으로 전환하여 프로필 수정 -> admin이므로 이제 200 OK 여야 함
    app.dependency_overrides[get_current_user] = lambda: "bob"
    response_update_admin = client.put(
        "/api/businesses/111-22-33333",
        json={
            "biz_id": "111-22-33333",
            "company_name": "수정성공앨리스테크",
            "ceo_name": "앨리스",
            "business_types": [],
            "licenses": [],
            "regions": [],
            "past_projects": [],
            "annual_revenue": 0,
            "employee_count": 0
        }
    )
    assert response_update_admin.status_code == 200

    # Clean up 의존성 오버라이드
    app.dependency_overrides.clear()
