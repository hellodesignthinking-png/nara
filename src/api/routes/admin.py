"""
관리자(Admin) API 라우트

시스템 전반(회원, 등록 회사, 협업 연계 상태)에 대한 모니터링 및
운영을 제어하는 관리자 전용 REST API입니다.
"""

import logging
from fastapi import APIRouter, Depends, HTTPException, status

from src.models.database import DatabaseManager
from ._helpers import get_db, get_admin_user
from ._models import AdminRoleUpdateRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/stats", summary="관리자 전역 통계 조회")
async def get_admin_stats(
    admin_user: str = Depends(get_admin_user),
    db: DatabaseManager = Depends(get_db)
):
    """
    시스템 가입 회원 수, 등록 회사 수, 총 관심공고 및 진행 중인 협업 프로젝트 수
    등의 메트릭 데이터를 반환합니다.
    """
    try:
        return db.get_admin_stats()
    except Exception as e:
        logger.error("관리자 통계 조회 실패 [관리자: %s]: %s", admin_user, e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="서버 통계 조회 중 오류가 발생했습니다."
        )


@router.get("/users", summary="전체 회원 리스트 조회")
async def get_users_for_admin(
    admin_user: str = Depends(get_admin_user),
    db: DatabaseManager = Depends(get_db)
):
    """
    시스템 내의 전체 가입 회원 리스트 및 개인 AI Persona 설정 요약을 조회합니다.
    """
    try:
        return db.get_all_users_for_admin()
    except Exception as e:
        logger.error("전체 회원 조회 실패 [관리자: %s]: %s", admin_user, e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="회원 목록 조회 중 오류가 발생했습니다."
        )


@router.put("/users/{username}/role", summary="회원 관리자 권한 수정")
async def update_user_role(
    username: str,
    req: AdminRoleUpdateRequest,
    admin_user: str = Depends(get_admin_user),
    db: DatabaseManager = Depends(get_db)
):
    """
    특정 회원의 관리자 여부(is_admin) 권한을 제어합니다.
    """
    if username == "admin":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="시스템 최고관리자(admin)의 권한은 해제할 수 없습니다."
        )
    try:
        success = db.update_user_admin_flag(username, req.is_admin)
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="권한을 수정할 대상 유저를 찾을 수 없습니다."
            )
        logger.info("회원 권한 업데이트 완료: %s -> is_admin=%s [관리자: %s]", username, req.is_admin, admin_user)
        return {"message": f"사용자 '{username}'의 관리자 권한이 {'부여' if req.is_admin else '해제'}되었습니다."}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("회원 권한 변경 중 오류 발생 [관리자: %s]: %s", admin_user, e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="권한 변경 도중 서버 오류가 발생했습니다."
        )


@router.delete("/users/{username}", summary="회원 강제 탈퇴 처리")
async def delete_user(
    username: str,
    admin_user: str = Depends(get_admin_user),
    db: DatabaseManager = Depends(get_db)
):
    """
    회원을 영구 강제 삭제 처리합니다 (최고관리자 제외).
    """
    if username == admin_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="자기 자신을 강제 탈퇴할 수 없습니다."
        )
    if username == "admin":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="최고 관리자 'admin' 계정은 삭제 불가능합니다."
        )
    try:
        success = db.delete_user_by_admin(username)
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="삭제할 대상 유저를 찾을 수 없습니다."
            )
        logger.info("회원 강제 삭제 성공: %s [관리자: %s]", username, admin_user)
        return {"message": f"사용자 '{username}'이(가) 강제 탈퇴 처리되었습니다."}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("회원 삭제 실패 [관리자: %s]: %s", admin_user, e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="회원 삭제 처리 도중 서버 오류가 발생했습니다."
        )


@router.get("/companies", summary="전체 등록 기업 현황 조회")
async def get_companies_for_admin(
    admin_user: str = Depends(get_admin_user),
    db: DatabaseManager = Depends(get_db)
):
    """
    시스템에 등록된 전체 회사 프로필 및 해당 기업에 참여 중인 직원(조직원) 인원 규모를 모니터링합니다.
    """
    try:
        return db.get_all_companies_for_admin()
    except Exception as e:
        logger.error("기업 현황 조회 실패 [관리자: %s]: %s", admin_user, e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="기업 현황 목록 조회 중 오류가 발생했습니다."
        )


@router.get("/collaborations", summary="전체 공동 수급 협업 현황 조회")
async def get_collaborations_for_admin(
    admin_user: str = Depends(get_admin_user),
    db: DatabaseManager = Depends(get_db)
):
    """
    동일한 공고번호에 다수 회원(2인 이상)들이 관심 등록하여 가점 및 파트너 관계를 매칭하고 있는
    공동 입찰 협업 현황을 일괄 모니터링합니다.
    """
    try:
        return db.get_all_collaborations_for_admin()
    except Exception as e:
        logger.error("협업 현황 조회 실패 [관리자: %s]: %s", admin_user, e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="협업 현황 목록 조회 중 오류가 발생했습니다."
        )

from pydantic import BaseModel
class AdminUserPasswordResetRequest(BaseModel):
    new_password: str

@router.delete("/companies/{biz_id}", summary="회사 프로필 강제 삭제")
async def delete_company_by_admin_route(
    biz_id: str,
    admin_user: str = Depends(get_admin_user),
    db: DatabaseManager = Depends(get_db)
):
    """
    관리자가 특정 회사 정보를 강제로 삭제 처리합니다.
    """
    try:
        success = db.delete_company_by_admin(biz_id)
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="삭제할 대상 기업을 찾을 수 없습니다."
            )
        logger.info("회사 강제 삭제 성공: %s [관리자: %s]", biz_id, admin_user)
        return {"message": f"회사 프로필(ID: {biz_id})이 강제 삭제되었습니다."}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("회사 삭제 실패 [관리자: %s]: %s", admin_user, e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="회사 삭제 도중 서버 오류가 발생했습니다."
        )

@router.post("/users/{username}/reset-password", summary="회원 비밀번호 강제 변경")
async def reset_user_password_by_admin(
    username: str,
    req: AdminUserPasswordResetRequest,
    admin_user: str = Depends(get_admin_user),
    db: DatabaseManager = Depends(get_db)
):
    """
    관리자가 특정 회원의 비밀번호를 강제로 재설정합니다.
    """
    if len(req.new_password) < 4:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="비밀번호는 최소 4자 이상이어야 합니다."
        )
    
    from .auth import hash_password
    password_hash = hash_password(req.new_password)
    
    conn = db._ensure_connection()
    try:
        ph = "%s" if db.is_postgres else "?"
        cursor = conn.execute(f"SELECT username FROM users WHERE username = {ph}", (username,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="비밀번호를 재설정할 대상 회원을 찾을 수 없습니다."
            )
        
        if not db.is_postgres:
            conn.execute("BEGIN TRANSACTION")
        conn.execute(
            f"UPDATE users SET password_hash = {ph} WHERE username = {ph}",
            (password_hash, username)
        )
        conn.commit()
        
        logger.info("회원 비밀번호 강제 변경 완료: %s [관리자: %s]", username, admin_user)
        return {"message": f"사용자 '{username}'의 비밀번호가 성공적으로 변경되었습니다."}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        logger.error("회원 비밀번호 강제 변경 실패 [관리자: %s]: %s", admin_user, e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="비밀번호 변경 중 서버 오류가 발생했습니다."
        )
