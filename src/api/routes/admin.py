"""
관리자(Admin) API 라우트 — 전면 강화 버전

회원, 회사, 협업, 공지사항, API 키, 시스템 통계, 공고 수집 제어 등
플랫폼 전체 운영을 위한 관리자 전용 API.
"""

import logging
import os
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel
from typing import Optional

from src.models.database import DatabaseManager
from ._helpers import get_db, get_admin_user, _load_settings, _save_settings
from ._models import AdminRoleUpdateRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


# ──────────────────────────────────────────────
# 공통 Pydantic 모델
# ──────────────────────────────────────────────

class AdminUserPasswordResetRequest(BaseModel):
    new_password: str

class NoticeCreateRequest(BaseModel):
    title: str
    content: str
    notice_type: str = "info"  # info | warning | critical
    is_active: bool = True

class SystemApiKeyRequest(BaseModel):
    data_go_kr_api_key: Optional[str] = None
    naver_client_id: Optional[str] = None
    naver_client_secret: Optional[str] = None
    youtube_api_key: Optional[str] = None
    kakao_api_key: Optional[str] = None
    gemini_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None
    google_analytics_id: Optional[str] = None

class UserMemoRequest(BaseModel):
    memo: str

class CompanyVerifyRequest(BaseModel):
    verified: bool


# ──────────────────────────────────────────────
# 1. 통계
# ──────────────────────────────────────────────

@router.get("/stats", summary="관리자 전역 통계 조회")
async def get_admin_stats(
    admin_user: str = Depends(get_admin_user),
    db: DatabaseManager = Depends(get_db)
):
    try:
        stats = db.get_admin_stats()
        # 추가 통계: 공고 수
        conn = db._ensure_connection()
        ph = "%s" if db.is_postgres else "?"
        try:
            cur = conn.execute("SELECT COUNT(*) FROM bid_announcements")
            row = cur.fetchone()
            stats["total_bids"] = row[0] if row else 0
        except Exception:
            stats["total_bids"] = 0
        try:
            today = datetime.now().strftime("%Y-%m-%d")
            cur = conn.execute(
                f"SELECT COUNT(*) FROM bid_announcements WHERE collected_at >= {ph}",
                (today,)
            )
            row = cur.fetchone()
            stats["today_bids"] = row[0] if row else 0
        except Exception:
            stats["today_bids"] = 0
        try:
            cur = conn.execute("SELECT COUNT(*) FROM users WHERE is_admin = 1 OR is_admin = true")
            row = cur.fetchone()
            stats["total_admins"] = row[0] if row else 0
        except Exception:
            stats["total_admins"] = 0
        return stats
    except Exception as e:
        logger.error("관리자 통계 조회 실패 [%s]: %s", admin_user, e)
        raise HTTPException(status_code=500, detail="통계 조회 실패")


# ──────────────────────────────────────────────
# 2. 회원 관리
# ──────────────────────────────────────────────

@router.get("/users", summary="전체 회원 리스트 조회")
async def get_users_for_admin(
    admin_user: str = Depends(get_admin_user),
    db: DatabaseManager = Depends(get_db)
):
    try:
        return db.get_all_users_for_admin()
    except Exception as e:
        logger.error("회원 조회 실패 [%s]: %s", admin_user, e)
        raise HTTPException(status_code=500, detail="회원 목록 조회 실패")


@router.put("/users/{username}/role", summary="회원 관리자 권한 수정")
async def update_user_role(
    username: str,
    req: AdminRoleUpdateRequest,
    admin_user: str = Depends(get_admin_user),
    db: DatabaseManager = Depends(get_db)
):
    if username == "admin":
        raise HTTPException(status_code=400, detail="최고관리자 권한은 해제 불가합니다.")
    try:
        success = db.update_user_admin_flag(username, req.is_admin)
        if not success:
            raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")
        logger.info("권한 업데이트: %s -> is_admin=%s [%s]", username, req.is_admin, admin_user)
        return {"message": f"{username}의 권한이 {'관리자' if req.is_admin else '일반회원'}으로 변경되었습니다."}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("권한 변경 실패 [%s]: %s", admin_user, e)
        raise HTTPException(status_code=500, detail="권한 변경 실패")


@router.delete("/users/{username}", summary="회원 강제 탈퇴")
async def delete_user(
    username: str,
    admin_user: str = Depends(get_admin_user),
    db: DatabaseManager = Depends(get_db)
):
    if username == admin_user or username == "admin":
        raise HTTPException(status_code=400, detail="이 계정은 삭제할 수 없습니다.")
    try:
        success = db.delete_user_by_admin(username)
        if not success:
            raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")
        logger.info("회원 강제 삭제: %s [%s]", username, admin_user)
        return {"message": f"{username}이(가) 탈퇴 처리되었습니다."}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("회원 삭제 실패 [%s]: %s", admin_user, e)
        raise HTTPException(status_code=500, detail="회원 삭제 실패")


@router.post("/users/{username}/reset-password", summary="회원 비밀번호 강제 변경")
async def reset_user_password_by_admin(
    username: str,
    req: AdminUserPasswordResetRequest,
    admin_user: str = Depends(get_admin_user),
    db: DatabaseManager = Depends(get_db)
):
    if len(req.new_password) < 4:
        raise HTTPException(status_code=400, detail="비밀번호는 최소 4자 이상이어야 합니다.")
    from .auth import hash_password
    password_hash = hash_password(req.new_password)
    conn = db._ensure_connection()
    try:
        ph = "%s" if db.is_postgres else "?"
        cursor = conn.execute(f"SELECT username FROM users WHERE username = {ph}", (username,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")
        if not db.is_postgres:
            conn.execute("BEGIN TRANSACTION")
        conn.execute(
            f"UPDATE users SET password_hash = {ph} WHERE username = {ph}",
            (password_hash, username)
        )
        conn.commit()
        logger.info("비밀번호 강제 변경: %s [%s]", username, admin_user)
        return {"message": f"{username}의 비밀번호가 변경되었습니다."}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        logger.error("비밀번호 변경 실패 [%s]: %s", admin_user, e)
        raise HTTPException(status_code=500, detail="비밀번호 변경 실패")


@router.put("/users/{username}/memo", summary="회원 관리자 메모 수정")
async def update_user_memo(
    username: str,
    req: UserMemoRequest,
    admin_user: str = Depends(get_admin_user),
    db: DatabaseManager = Depends(get_db)
):
    conn = db._ensure_connection()
    try:
        ph = "%s" if db.is_postgres else "?"
        # admin_memo 컬럼이 없으면 무시
        try:
            if not db.is_postgres:
                conn.execute("BEGIN TRANSACTION")
            conn.execute(
                f"UPDATE users SET admin_memo = {ph} WHERE username = {ph}",
                (req.memo, username)
            )
            conn.commit()
        except Exception:
            conn.rollback()
            # 컬럼 없음 — 무시
        return {"message": "메모가 저장되었습니다."}
    except Exception as e:
        logger.error("메모 저장 실패: %s", e)
        raise HTTPException(status_code=500, detail="메모 저장 실패")


# ──────────────────────────────────────────────
# 3. 회사 관리
# ──────────────────────────────────────────────

@router.get("/companies", summary="전체 등록 기업 조회")
async def get_companies_for_admin(
    admin_user: str = Depends(get_admin_user),
    db: DatabaseManager = Depends(get_db)
):
    try:
        return db.get_all_companies_for_admin()
    except Exception as e:
        logger.error("기업 조회 실패 [%s]: %s", admin_user, e)
        raise HTTPException(status_code=500, detail="기업 목록 조회 실패")


@router.delete("/companies/{biz_id}", summary="회사 프로필 강제 삭제")
async def delete_company_by_admin_route(
    biz_id: str,
    admin_user: str = Depends(get_admin_user),
    db: DatabaseManager = Depends(get_db)
):
    try:
        success = db.delete_company_by_admin(biz_id)
        if not success:
            raise HTTPException(status_code=404, detail="기업을 찾을 수 없습니다.")
        logger.info("회사 삭제: %s [%s]", biz_id, admin_user)
        return {"message": f"회사(ID: {biz_id})가 삭제되었습니다."}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("회사 삭제 실패 [%s]: %s", admin_user, e)
        raise HTTPException(status_code=500, detail="회사 삭제 실패")


# ──────────────────────────────────────────────
# 4. 협업 현황
# ──────────────────────────────────────────────

@router.get("/collaborations", summary="전체 협업 현황 조회")
async def get_collaborations_for_admin(
    admin_user: str = Depends(get_admin_user),
    db: DatabaseManager = Depends(get_db)
):
    try:
        return db.get_all_collaborations_for_admin()
    except Exception as e:
        logger.error("협업 조회 실패 [%s]: %s", admin_user, e)
        raise HTTPException(status_code=500, detail="협업 현황 조회 실패")


# ──────────────────────────────────────────────
# 5. API 키 통합 관리
# ──────────────────────────────────────────────

@router.get("/api-keys", summary="시스템 API 키 현황 조회")
async def get_system_api_keys(
    admin_user: str = Depends(get_admin_user)
):
    """관리자용 API 키 전체 현황 (마스킹 처리)"""
    from src.config import load_config
    config = load_config()
    user_settings = _load_settings()

    def mask(val):
        if not val:
            return {"set": False, "masked": ""}
        s = str(val)
        if len(s) <= 8:
            return {"set": True, "masked": "****"}
        return {"set": True, "masked": s[:4] + "****" + s[-4:]}

    return {
        "data_go_kr_api_key": mask(config.data_go_kr_api_key or user_settings.get("data_go_kr_api_key")),
        "naver_client_id": mask(config.naver_client_id or user_settings.get("naver_client_id")),
        "naver_client_secret": mask(config.naver_client_secret or user_settings.get("naver_client_secret")),
        "youtube_api_key": mask(user_settings.get("youtube_api_key")),
        "kakao_api_key": mask(user_settings.get("kakao_api_key")),
        "gemini_api_key": mask(config.gemini_api_key or os.getenv("GEMINI_API_KEY") or user_settings.get("gemini_api_key")),
        "openai_api_key": mask(config.openai_api_key or os.getenv("OPENAI_API_KEY") or user_settings.get("openai_api_key")),
        "google_analytics_id": mask(user_settings.get("google_analytics_id")),
    }


@router.put("/api-keys", summary="시스템 API 키 저장")
async def save_system_api_keys(
    req: SystemApiKeyRequest,
    admin_user: str = Depends(get_admin_user)
):
    """관리자가 시스템 공용 API 키를 설정"""
    settings = _load_settings()
    updated = []

    fields = [
        ("data_go_kr_api_key", req.data_go_kr_api_key),
        ("naver_client_id", req.naver_client_id),
        ("naver_client_secret", req.naver_client_secret),
        ("youtube_api_key", req.youtube_api_key),
        ("kakao_api_key", req.kakao_api_key),
        ("gemini_api_key", req.gemini_api_key),
        ("openai_api_key", req.openai_api_key),
        ("google_analytics_id", req.google_analytics_id),
    ]

    for field_name, value in fields:
        if value is not None and value.strip():
            settings[field_name] = value.strip()
            updated.append(field_name)
            # 환경변수에도 즉시 반영
            os.environ[field_name.upper()] = value.strip()

    if not updated:
        raise HTTPException(status_code=400, detail="저장할 키를 하나 이상 입력해주세요.")

    _save_settings(settings)
    try:
        from src.config import reload_config
        reload_config()
    except Exception:
        pass

    logger.info("API 키 저장: %s [관리자: %s]", updated, admin_user)
    return {"message": f"{len(updated)}개 API 키가 저장되었습니다.", "updated": updated}


# ──────────────────────────────────────────────
# 6. 공고 현황
# ──────────────────────────────────────────────

@router.get("/bids/stats", summary="공고 수집 현황 조회")
async def get_bids_stats(
    admin_user: str = Depends(get_admin_user),
    db: DatabaseManager = Depends(get_db)
):
    conn = db._ensure_connection()
    try:
        ph = "%s" if db.is_postgres else "?"
        stats = {}
        # 총 공고 수
        cur = conn.execute("SELECT COUNT(*) FROM bid_announcements")
        stats["total"] = cur.fetchone()[0]
        # 오늘 수집
        today = datetime.now().strftime("%Y-%m-%d")
        cur = conn.execute(
            f"SELECT COUNT(*) FROM bid_announcements WHERE collected_at >= {ph}", (today,)
        )
        stats["today"] = cur.fetchone()[0]
        # 카테고리별
        try:
            cur = conn.execute(
                "SELECT category, COUNT(*) as cnt FROM bid_announcements GROUP BY category ORDER BY cnt DESC LIMIT 10"
            )
            stats["by_category"] = [{"category": r[0] or "미분류", "count": r[1]} for r in cur.fetchall()]
        except Exception:
            stats["by_category"] = []
        # 최근 수집 시각
        try:
            cur = conn.execute("SELECT MAX(collected_at) FROM bid_announcements")
            stats["last_collected"] = cur.fetchone()[0]
        except Exception:
            stats["last_collected"] = None
        return stats
    except Exception as e:
        logger.error("공고 통계 조회 실패: %s", e)
        raise HTTPException(status_code=500, detail="공고 통계 조회 실패")


@router.post("/bids/collect", summary="공고 수집 수동 트리거")
async def trigger_bid_collection(
    admin_user: str = Depends(get_admin_user)
):
    """관리자가 수동으로 공고 수집을 트리거합니다."""
    try:
        from src.api.app import scheduled_analysis_job
        import asyncio
        asyncio.create_task(scheduled_analysis_job())
        return {"message": "공고 수집이 시작되었습니다. 잠시 후 결과를 확인하세요."}
    except Exception as e:
        logger.error("공고 수집 트리거 실패: %s", e)
        raise HTTPException(status_code=500, detail=f"수집 실패: {str(e)}")


# ──────────────────────────────────────────────
# 7. 시스템 정보
# ──────────────────────────────────────────────

@router.get("/system/info", summary="시스템 정보 조회")
async def get_system_info(
    admin_user: str = Depends(get_admin_user)
):
    """서버 환경변수, 버전, DB 상태 등 시스템 정보"""
    import sys
    from src.config import load_config
    config = load_config()

    env_keys = [
        "RENDER", "IS_PRODUCTION", "SUPABASE_DB_URL",
        "SCHEDULER_ENABLED", "SCHEDULE_HOUR", "SCHEDULE_MINUTE",
    ]
    env_info = {k: ("설정됨" if os.getenv(k) else "미설정") for k in env_keys}
    # 민감한 값은 마스킹
    if os.getenv("SUPABASE_DB_URL"):
        env_info["SUPABASE_DB_URL"] = "설정됨 (마스킹)"

    return {
        "version": "1.1.0",
        "python_version": sys.version.split()[0],
        "environment": "production" if os.getenv("RENDER") or os.getenv("IS_PRODUCTION") else "development",
        "db_mode": "PostgreSQL (Supabase)" if os.getenv("SUPABASE_DB_URL") or os.getenv("DATABASE_URL") else "SQLite",
        "env": env_info,
        "scheduler_enabled": os.getenv("SCHEDULER_ENABLED", "true").lower() in ("true", "1"),
    }
