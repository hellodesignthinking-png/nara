"""
기획서 및 제안서 공유 게시판 API 라우터
"""

import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status, Request
from pydantic import BaseModel

from src.models.database import DatabaseManager
from ._helpers import get_db, get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/proposals", tags=["proposals"])

# Pydantic 모델
class ProposalAddRequest(BaseModel):
    title: str
    category: str  # 제안서, 기획서, 템플릿, 기타
    content: str
    file_url: Optional[str] = None

@router.get("", summary="제안서/기획서 목록 조회")
async def get_proposal_list(
    category: Optional[str] = None,
    keyword: Optional[str] = None,
    db: DatabaseManager = Depends(get_db)
):
    """
    등록된 제안서 및 기획서 리스트를 필터링하여 조회합니다.
    """
    try:
        return db.get_proposals(category, keyword)
    except Exception as e:
        logger.error("제안서 목록 조회 에러: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="목록을 불러오는 중 서버 오류가 발생했습니다."
        )

@router.post("", summary="제안서/기획서 등록")
async def add_proposal(
    req: ProposalAddRequest,
    current_user: str = Depends(get_current_user),
    db: DatabaseManager = Depends(get_db)
):
    """
    새로운 제안서, 기획서, 또는 템플릿 공유 글을 등록합니다. (로그인 필요)
    """
    title = req.title.strip()
    category = req.category.strip()
    content = req.content.strip()
    
    if not title or not category or not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="제목, 카테고리, 내용은 필수 입력값입니다."
        )
        
    try:
        db.add_proposal(current_user, title, category, content, req.file_url)
        return {"message": "기획서가 등록되었습니다.", "title": title}
    except Exception as e:
        logger.error("제안서 등록 실패 [유저: %s]: %s", current_user, e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="기획서 등록에 실패했습니다."
        )

@router.delete("/{proposal_id}", summary="제안서/기획서 삭제")
async def delete_proposal(
    proposal_id: int,
    current_user: str = Depends(get_current_user),
    db: DatabaseManager = Depends(get_db)
):
    """
    등록한 제안서/기획서 글을 삭제합니다. (작성자 또는 관리자 전용)
    """
    # 1. 글 상세 조회하여 작성자 대조
    conn = db._ensure_connection()
    try:
        ph = "%s" if db.is_postgres else "?"
        cursor = conn.execute(f"SELECT username FROM proposal_shares WHERE id = {ph}", (proposal_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="삭제할 게시글을 찾을 수 없습니다."
            )
            
        # 2. 권한 확인 (작성자이거나 관리자인가?)
        is_admin = False
        user_cursor = conn.execute(f"SELECT is_admin FROM users WHERE username = {ph}", (current_user,))
        user_row = user_cursor.fetchone()
        if user_row:
            is_admin = bool(user_row["is_admin"] if isinstance(user_row, dict) else user_row[0])
            
        row_username = row["username"] if isinstance(row, dict) else row[0]
        if row_username != current_user and not is_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="본인이 작성한 글만 삭제할 수 있습니다."
            )
            
        # 3. 삭제
        success = db.delete_proposal(proposal_id)
        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="게시글 삭제 처리에 실패했습니다."
            )
            
        return {"message": "제안서 공유글이 정상적으로 삭제되었습니다."}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("제안서 삭제 오류: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="삭제 중 서버 오류가 발생했습니다."
        )

@router.post("/{proposal_id}/download", summary="다운로드(조회) 수 증가")
async def increment_downloads(
    proposal_id: int,
    db: DatabaseManager = Depends(get_db)
):
    """
    제안서/기획서 다운로드 링크 클릭 시 다운로드 카운트를 증가시킵니다.
    """
    try:
        db.increment_proposal_downloads(proposal_id)
        return {"message": "다운로드 수 증가 완료"}
    except Exception as e:
        logger.error("다운로드 수 증가 실패 [ID: %s]: %s", proposal_id, e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="다운로드 카운트 증가 중 오류 발생"
        )
