"""
회원 인증 및 토큰 관리 API 라우터

외부 라이브러리(python-jose, passlib 등) 종속성 없이 
파이썬 표준 라이브러리(hashlib, hmac, base64)를 활용하여 
비밀번호 PBKDF2 해싱 및 JWT 발급을 직접 구현합니다.
"""

import base64
import json
import hmac
import hashlib
import time
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response, Request, status
from pydantic import BaseModel, EmailStr

from src.models.schemas import BusinessProfile
from src.models.database import DatabaseManager
from ._helpers import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

# JWT 설정
SECRET_KEY = "nara_analyzer_super_secret_key_change_me_in_production"
TOKEN_EXPIRE_SECONDS = 86400  # 1일

# ──────────────────────────────────────────────
# Pydantic 모델
# ──────────────────────────────────────────────

class UserRegisterRequest(BaseModel):
    username: str
    password: str
    email: Optional[EmailStr] = None

class UserLoginRequest(BaseModel):
    username: str
    password: str

# ──────────────────────────────────────────────
# 보안 및 암호화 유틸리티
# ──────────────────────────────────────────────

def hash_password(password: str) -> str:
    """비밀번호를 PBKDF2-HMAC-SHA256 알고리즘으로 안전하게 해싱합니다."""
    import secrets
    salt = secrets.token_hex(16)
    hash_bytes = hashlib.pbkdf2_hmac(
        'sha256',
        password.encode('utf-8'),
        salt.encode('utf-8'),
        100000
    )
    return f"pbkdf2_sha256$100000${salt}${hash_bytes.hex()}"

def verify_password(password: str, hashed: str) -> bool:
    """입력된 비밀번호가 저장된 해시와 일치하는지 검증합니다."""
    import secrets
    try:
        parts = hashed.split('$')
        if len(parts) != 4 or parts[0] != 'pbkdf2_sha256':
            return False
        iterations = int(parts[1])
        salt = parts[2]
        hash_hex = parts[3]
        
        test_hash = hashlib.pbkdf2_hmac(
            'sha256',
            password.encode('utf-8'),
            salt.encode('utf-8'),
            iterations
        )
        return secrets.compare_digest(test_hash.hex(), hash_hex)
    except Exception:
        return False

def _b64url_encode(data: bytes) -> str:
    """Base64URL 인코딩을 수행합니다 (패딩 생략)."""
    return base64.urlsafe_b64encode(data).decode('utf-8').rstrip('=')

def _b64url_decode(data: str) -> bytes:
    """Base64URL 디코딩을 수행합니다 (패딩 복구)."""
    padding = '=' * (4 - len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)

def create_jwt(payload: dict, expires_in: int = TOKEN_EXPIRE_SECONDS) -> str:
    """HMAC-SHA256 서명 기반 자가서명 JWT 토큰을 발급합니다."""
    header = {"alg": "HS256", "typ": "JWT"}
    payload = payload.copy()
    payload["exp"] = int(time.time()) + expires_in
    
    header_json = json.dumps(header, separators=(',', ':')).encode('utf-8')
    payload_json = json.dumps(payload, separators=(',', ':')).encode('utf-8')
    
    header_b64 = _b64url_encode(header_json)
    payload_b64 = _b64url_encode(payload_json)
    
    signature_input = f"{header_b64}.{payload_b64}".encode('utf-8')
    sig = hmac.new(SECRET_KEY.encode('utf-8'), signature_input, hashlib.sha256).digest()
    sig_b64 = _b64url_encode(sig)
    
    return f"{header_b64}.{payload_b64}.{sig_b64}"

def decode_jwt(token: str) -> Optional[dict]:
    """JWT 토큰의 무결성 및 만료 여부를 검증한 후 페이로드를 반환합니다."""
    try:
        parts = token.split('.')
        if len(parts) != 3:
            return None
        header_b64, payload_b64, sig_b64 = parts
        
        signature_input = f"{header_b64}.{payload_b64}".encode('utf-8')
        expected_sig = hmac.new(SECRET_KEY.encode('utf-8'), signature_input, hashlib.sha256).digest()
        expected_sig_b64 = _b64url_encode(expected_sig)
        
        if not hmac.compare_digest(sig_b64, expected_sig_b64):
            return None
        
        payload = json.loads(_b64url_decode(payload_b64).decode('utf-8'))
        if payload.get("exp", 0) < time.time():
            return None  # 토큰 만료
            
        return payload
    except Exception:
        return None

# ──────────────────────────────────────────────
# 엔드포인트 구현
# ──────────────────────────────────────────────

@router.post("/register", summary="회원 가입")
async def register(request: UserRegisterRequest, db: DatabaseManager = Depends(get_db)):
    """
    새로운 사용자를 등록합니다.
    """
    username = request.username.strip()
    if not username:
        raise HTTPException(status_code=400, detail="사용자명(username)은 필수입니다.")
    if len(request.password) < 4:
        raise HTTPException(status_code=400, detail="비밀번호는 최소 4자 이상이어야 합니다.")
        
    existing_user = db.get_user(username)
    if existing_user:
        raise HTTPException(status_code=400, detail="이미 존재하는 사용자명입니다.")
        
    password_hash = hash_password(request.password)
    try:
        db.add_user(username, password_hash, request.email)
        logger.info("회원 가입 성공: %s", username)
        return {"message": "회원 가입이 완료되었습니다.", "username": username}
    except Exception as e:
        logger.error("회원 가입 처리 실패: %s", e)
        raise HTTPException(status_code=500, detail="회원 등록 중 서버 오류가 발생했습니다.")

@router.post("/login", summary="로그인")
async def login(request: UserLoginRequest, response: Response, db: DatabaseManager = Depends(get_db)):
    """
    사용자명과 비밀번호를 검증하고 HttpOnly 쿠키로 JWT 액세스 토큰을 발급합니다.
    """
    username = request.username.strip()
    user = db.get_user(username)
    
    if not user or not verify_password(request.password, user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="사용자명 또는 비밀번호가 올바르지 않습니다."
        )
        
    token = create_jwt({"sub": username})
    
    # HttpOnly 쿠키 설정
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        max_age=TOKEN_EXPIRE_SECONDS,
        expires=TOKEN_EXPIRE_SECONDS,
        samesite="lax",
        secure=False  # 개발 및 배포 환경에 따라 필요시 True로 변경
    )
    
    logger.info("사용자 로그인 완료: %s", username)
    return {"message": "로그인에 성공했습니다.", "username": username}

@router.post("/logout", summary="로그아웃")
async def logout(response: Response):
    """
    HttpOnly 쿠키로 발급된 JWT 토큰을 만료시켜 로그아웃을 처리합니다.
    """
    response.delete_cookie(key="access_token")
    return {"message": "로그아웃되었습니다."}

@router.get("/me", summary="현재 로그인 유저 정보 조회")
async def get_me(request: Request, db: DatabaseManager = Depends(get_db)):
    """
    쿠키에서 JWT 토큰을 해독하여 현재 로그인된 사용자의 ID와 관리자 여부를 반환합니다.
    """
    token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="로그인이 필요합니다."
        )
        
    payload = decode_jwt(token)
    if not payload or not payload.get("sub"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="인증 토큰이 유효하지 않거나 만료되었습니다."
        )
        
    username = payload["sub"]
    user = db.get_user(username)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="사용자 정보가 존재하지 않습니다."
        )
        
    return {
        "username": username,
        "is_admin": bool(user.get("is_admin", 0))
    }
