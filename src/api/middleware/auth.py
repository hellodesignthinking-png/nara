"""
API 인증 미들웨어

API Key 기반 간단 인증을 제공합니다.
환경변수 NARA_API_KEY가 설정되어 있을 때만 인증이 활성화됩니다.
DEV_MODE=true로 설정하면 인증을 비활성화할 수 있습니다.
"""

import os
import hmac
import logging
import time
from collections import defaultdict
from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

# 인증이 필요 없는 경로 목록
PUBLIC_PATHS = {
    "/",
    "/health",
    "/docs",
    "/openapi.json",
    "/redoc",
    "/favicon.ico",
}

# 인증이 필요 없는 경로 접두사
PUBLIC_PREFIXES = (
    "/static",
)


class APIKeyAuthMiddleware(BaseHTTPMiddleware):
    """
    API Key 기반 인증 미들웨어
    
    인증 방법:
    1. 헤더: X-API-Key: <key>
    2. 쿼리 파라미터: ?api_key=<key>
    
    환경변수:
    - NARA_API_KEY: API 키 (미설정 시 인증 비활성화)
    - DEV_MODE: true로 설정 시 인증 비활성화
    """

    # 기본 속도 제한 설정: IP당 최대 실패 횟수 및 차단 시간(초)
    MAX_FAILED_ATTEMPTS = 10
    BLOCK_DURATION_SECONDS = 300  # 5분

    def __init__(self, app):
        super().__init__(app)
        # IP별 실패 기록: {ip: [(timestamp, ...), ...]}
        self._failed_attempts: dict[str, list[float]] = defaultdict(list)

    def _is_rate_limited(self, client_ip: str) -> bool:
        """해당 IP의 인증 실패 횟수가 제한을 초과했는지 확인합니다."""
        now = time.time()
        cutoff = now - self.BLOCK_DURATION_SECONDS
        # 만료된 기록 제거
        self._failed_attempts[client_ip] = [
            t for t in self._failed_attempts[client_ip] if t > cutoff
        ]
        return len(self._failed_attempts[client_ip]) >= self.MAX_FAILED_ATTEMPTS

    def _record_failed_attempt(self, client_ip: str) -> None:
        """인증 실패를 기록합니다."""
        self._failed_attempts[client_ip].append(time.time())

    async def dispatch(self, request: Request, call_next):
        # CORS preflight (OPTIONS) 요청은 인증 없이 통과
        if request.method == "OPTIONS":
            response = await call_next(request)
            return response

        # DEV_MODE이면 인증 스킵
        if os.getenv("DEV_MODE", "").lower() in ("true", "1", "yes"):
            return await call_next(request)

        # API 키가 설정되지 않았으면 인증 스킵 (첨 설정 전)
        api_key = os.getenv("NARA_API_KEY", "")
        if not api_key:
            return await call_next(request)

        # 공개 경로는 인증 스킵
        path = request.url.path
        if path in PUBLIC_PATHS:
            return await call_next(request)
        if any(path.startswith(prefix) for prefix in PUBLIC_PREFIXES):
            return await call_next(request)

        # 속도 제한 확인
        client_ip = request.client.host if request.client else "unknown"
        if self._is_rate_limited(client_ip):
            logger.warning(
                "속도 제한 초과: %s %s (IP: %s)",
                request.method, path, client_ip,
            )
            return JSONResponse(
                status_code=429,
                content={"detail": "너무 많은 인증 실패. 잠시 후 다시 시도하세요."},
            )

        # 인증 확인
        request_key = (
            request.headers.get("X-API-Key")
            or request.query_params.get("api_key")
        )

        if not hmac.compare_digest(request_key or "", api_key):
            user_agent = request.headers.get("User-Agent", "unknown")
            self._record_failed_attempt(client_ip)
            logger.warning(
                "인증 실패: %s %s (IP: %s, User-Agent: %s)",
                request.method, path, client_ip, user_agent,
            )
            return JSONResponse(
                status_code=401,
                content={"detail": "유효하지 않은 API 키입니다."},
            )

        return await call_next(request)
