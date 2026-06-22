"""
설정 API 라우트

/settings/*, /scheduler/*, /slack/* 엔드포인트:
시스템 설정 조회/변경, 스케줄러 제어, Slack 연동
"""

import logging
import os
import tempfile
import httpx
from pathlib import Path as _Path

from fastapi import APIRouter, Body, HTTPException, Depends

from src.config import load_config, reload_config
from src.models.database import DatabaseManager

from ._helpers import _load_settings, _save_settings, get_db, get_current_user, get_admin_user
from ._models import (
    KeywordsUpdateRequest,
    RelevanceUpdateRequest,
    ScheduleUpdateRequest,
    SlackWebhookRequest,
    ApiKeyTestRequest,
    AISettingsUpdateRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["settings"])


# ──────────────────────────────────────────────
# 설정 API
# ──────────────────────────────────────────────


@router.get("/settings", summary="현재 설정 조회")
async def get_settings():
    """
    현재 시스템 설정을 조회합니다.

    API 키는 보안을 위해 마스킹 처리되며,
    설정 여부(true/false)만 반환합니다.
    """
    try:
        config = load_config()

        return {
            "keywords": config.keywords,
            "min_relevance_score": config.min_relevance_score,
            "past_years": config.past_years,
            "openai_model": config.openai_model,
            "api_keys": {
                "data_go_kr": bool(config.data_go_kr_api_key),
                "naver": bool(config.naver_client_id and config.naver_client_secret),
                "openai": bool(config.openai_api_key),
            },
            "email": {
                "configured": bool(config.smtp_user),
                "recipients_count": len(config.email_recipients),
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("설정 조회 실패: %s", e)
        raise HTTPException(status_code=500, detail="서버 내부 오류가 발생했습니다")


@router.get("/settings/full", summary="전체 설정 조회 (웹 UI용)")
async def get_settings_full():
    """
    .env 설정과 settings.json을 병합하여 전체 설정을 반환합니다.
    settings.json의 값이 .env 값을 오버라이드합니다.
    """
    try:
        config = load_config()
        user_settings = _load_settings()

        keywords = user_settings.get("keywords") or config.keywords
        exclude_keywords = user_settings.get("exclude_keywords") or []
        min_score = user_settings.get("min_relevance_score", config.min_relevance_score)

        return {
            "keywords": keywords,
            "exclude_keywords": exclude_keywords,
            "min_relevance_score": min_score,
            "past_years": config.past_years,
            "api_status": {
                "data_go_kr": bool(config.data_go_kr_api_key),
                "naver": bool(config.naver_client_id and config.naver_client_secret),
                "openai": bool(config.openai_api_key),
            },
            "notification": {
                "email_configured": bool(config.smtp_user),
                "recipients_count": len(config.email_recipients),
                "schedule_time": user_settings.get("schedule_time", "08:00"),
            },
            "slack_webhook_url": user_settings.get("slack_webhook_url", ""),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("전체 설정 조회 실패: %s", e)
        raise HTTPException(status_code=500, detail="서버 내부 오류가 발생했습니다")


@router.put("/settings/keywords", summary="키워드 설정 업데이트")
async def update_keywords(request: KeywordsUpdateRequest):
    """관심 키워드와 제외 키워드를 업데이트합니다."""
    try:
        settings = _load_settings()
        settings["keywords"] = request.keywords
        settings["exclude_keywords"] = request.exclude_keywords
        _save_settings(settings)

        logger.info("키워드 업데이트: %d개 관심, %d개 제외",
                     len(request.keywords), len(request.exclude_keywords))
        return {
            "message": "키워드가 업데이트되었습니다.",
            "keywords": request.keywords,
            "exclude_keywords": request.exclude_keywords,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("키워드 업데이트 실패: %s", e)
        raise HTTPException(status_code=500, detail="서버 내부 오류가 발생했습니다")


@router.put("/settings/relevance", summary="관련도 설정 업데이트")
async def update_relevance(request: RelevanceUpdateRequest):
    """최소 관련도 점수를 업데이트합니다."""
    try:
        settings = _load_settings()
        settings["min_relevance_score"] = request.min_relevance_score
        _save_settings(settings)

        logger.info("관련도 점수 업데이트: %d", request.min_relevance_score)
        return {
            "message": "관련도 설정이 업데이트되었습니다.",
            "min_relevance_score": request.min_relevance_score,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("관련도 업데이트 실패: %s", e)
        raise HTTPException(status_code=500, detail="서버 내부 오류가 발생했습니다")


@router.put("/settings/api-keys", summary="API 키 업데이트")
async def update_api_keys(
    request: dict = Body(...),
    current_user: dict = Depends(get_current_user),
    db: DatabaseManager = Depends(get_db)
):
    """
    API 키를 업데이트합니다.
    어드민이고 시스템 전체 키를 수정하려는 경우 .env를 업데이트합니다.
    그 외 일반 사용자 및 AI 키 설정 요청인 경우 사용자의 개인 AI 설정을 업데이트합니다.
    """
    try:
        is_admin = current_user.get("is_admin", False) or current_user.get("username") == "admin"
        
        # 시스템 전체 설정에 속하는 필드들
        system_fields = {
            "data_go_kr_api_key",
            "naver_client_id",
            "naver_client_secret",
            "youtube_api_key",
            "kakao_api_key",
            "google_analytics_id"
        }
        
        # 요청에 시스템 필드가 하나라도 포함되어 있는지 검사
        has_system_field = any(field in request for field in system_fields)
        
        if has_system_field:
            if not is_admin:
                raise HTTPException(status_code=403, detail="시스템 전체 API 키를 변경할 권한이 없습니다.")
            
            # 어드민용 시스템 .env 설정 갱신 로직 실행
            env_path = _Path(__file__).resolve().parent.parent.parent.parent / ".env"
            env_map = {
                "data_go_kr_api_key": "DATA_GO_KR_API_KEY",
                "naver_client_id": "NAVER_CLIENT_ID",
                "naver_client_secret": "NAVER_CLIENT_SECRET",
                "openai_api_key": "OPENAI_API_KEY",
                "gemini_api_key": "GEMINI_API_KEY",
                "llm_engine": "LLM_ENGINE",
                "youtube_api_key": "YOUTUBE_API_KEY",
                "kakao_api_key": "KAKAO_API_KEY",
                "google_analytics_id": "GOOGLE_ANALYTICS_ID",
            }

            env_lines = []
            if env_path.exists():
                env_lines = env_path.read_text(encoding="utf-8").splitlines()

            updated_keys = []
            for field, env_var in env_map.items():
                value = request.get(field)
                if value is None:
                    continue
                value = value.strip()

                found = False
                for i, line in enumerate(env_lines):
                    if line.startswith(f"{env_var}=") or line.startswith(f"# {env_var}="):
                        env_lines[i] = f"{env_var}={value}"
                        found = True
                        break
                if not found:
                    env_lines.append(f"{env_var}={value}")

                os.environ[env_var] = value
                updated_keys.append(field)

            new_content = "\n".join(env_lines) + "\n"
            temp_fd, temp_path = tempfile.mkstemp(dir=str(env_path.parent))
            try:
                with os.fdopen(temp_fd, 'w', encoding='utf-8') as tmp:
                    tmp.write(new_content)
                os.rename(temp_path, str(env_path))
            except Exception:
                os.unlink(temp_path)
                raise

            try:
                reload_config()
            except Exception:
                pass

            logger.info("시스템 API 키 업데이트(어드민): %s", updated_keys)
            return {
                "message": f"시스템 API 키가 업데이트되었습니다: {', '.join(updated_keys)}",
                "updated": updated_keys,
            }
        
        # 개인 AI 설정 갱신 로직 실행 (openai_api_key, gemini_api_key, llm_engine)
        openai_key = request.get("openai_api_key")
        gemini_key = request.get("gemini_api_key")
        llm_engine = request.get("llm_engine")
        
        ai_settings = {}
        if openai_key is not None:
            ai_settings["openai_api_key"] = openai_key
        if gemini_key is not None:
            ai_settings["gemini_api_key"] = gemini_key
        if llm_engine is not None:
            ai_settings["llm_engine"] = llm_engine
            
        if not ai_settings:
            raise HTTPException(status_code=400, detail="변경할 AI 키 또는 설정을 입력해주세요.")
            
        username = current_user.get("username")
        # 기존 user_ai_settings를 가져와 덮어씌움
        existing = db.get_user_ai_settings(username) or {}
        for k, v in ai_settings.items():
            existing[k] = v
            
        success = db.save_user_ai_settings(username, existing)
        if not success:
            raise HTTPException(status_code=500, detail="개인 AI 설정을 저장하지 못했습니다.")
            
        logger.info("개인 AI 설정 업데이트 [유저: %s]: %s", username, list(ai_settings.keys()))
        return {
            "message": "개인 AI 설정이 성공적으로 저장되었습니다.",
            "updated": list(ai_settings.keys())
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("API 키 업데이트 실패: %s", e)
        raise HTTPException(status_code=500, detail="서버 내부 오류가 발생했습니다")


@router.get("/settings/api-keys", summary="API 키 상태 조회 (마스킹)")
async def get_api_keys_masked(
    current_user: dict = Depends(get_current_user),
    db: DatabaseManager = Depends(get_db)
):
    """API 키 설정 여부와 마스킹된 값을 반환합니다. 일반 사용자의 경우 본인의 개인 설정을 우선 노출합니다."""
    try:
        config = load_config()
        username = current_user.get("username")
        user_settings = db.get_user_ai_settings(username) or {}

        def mask(val):
            if not val:
                return ""
            if len(val) <= 8:
                return "****"
            return val[:4] + "*" * (len(val) - 8) + val[-4:]

        # 개인 설정값
        user_openai = user_settings.get("openai_api_key")
        user_gemini = user_settings.get("gemini_api_key")
        user_llm = user_settings.get("llm_engine")

        # 시스템 공용값
        sys_openai = config.openai_api_key
        sys_gemini = getattr(config, 'gemini_api_key', '')
        sys_llm = getattr(config, 'llm_engine', 'openai')

        # 1. OpenAI 결정
        openai_key_val = user_openai if user_openai is not None else sys_openai
        # 2. Gemini 결정
        gemini_key_val = user_gemini if user_gemini is not None else sys_gemini
        # 3. LLM 엔진 결정
        llm_val = user_llm if user_llm is not None else sys_llm

        return {
            "data_go_kr_api_key": {
                "set": bool(config.data_go_kr_api_key),
                "masked": mask(config.data_go_kr_api_key),
            },
            "naver_client_id": {
                "set": bool(config.naver_client_id),
                "masked": mask(config.naver_client_id),
            },
            "naver_client_secret": {
                "set": bool(getattr(config, 'naver_client_secret', '')),
                "masked": mask(getattr(config, 'naver_client_secret', '')),
            },
            "openai_api_key": {
                "set": bool(openai_key_val),
                "masked": mask(openai_key_val),
                "is_personal": user_openai is not None,
            },
            "gemini_api_key": {
                "set": bool(gemini_key_val),
                "masked": mask(gemini_key_val),
                "is_personal": user_gemini is not None,
            },
            "llm_engine": {
                "set": True,
                "masked": llm_val,
                "is_personal": user_llm is not None,
            },
            "youtube_api_key": {
                "set": bool(getattr(config, 'youtube_api_key', '')),
                "masked": mask(getattr(config, 'youtube_api_key', '')),
            },
            "kakao_api_key": {
                "set": bool(getattr(config, 'kakao_api_key', '')),
                "masked": mask(getattr(config, 'kakao_api_key', '')),
            },
            "google_analytics_id": {
                "set": bool(getattr(config, 'google_analytics_id', '')),
                "masked": getattr(config, 'google_analytics_id', ''),
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("API 키 상태 조회 실패: %s", e)
        raise HTTPException(status_code=500, detail="서버 내부 오류가 발생했습니다")


# ──────────────────────────────────────────────
# 스케줄러 API
# ──────────────────────────────────────────────


@router.get("/scheduler/status", summary="스케줄러 상태 조회")
async def get_scheduler_status():
    """자동 스케줄러의 현재 상태를 반환합니다."""
    try:
        from src.api.app_state import scheduler
        if scheduler is None:
            raise HTTPException(status_code=503, detail="스케줄러가 초기화되지 않았습니다")
        return scheduler.get_status()
    except HTTPException:
        raise
    except Exception as e:
        logger.error("스케줄러 상태 조회 실패: %s", e)
        raise HTTPException(status_code=500, detail="서버 내부 오류가 발생했습니다")


@router.post("/scheduler/run-now", summary="즉시 실행")
async def scheduler_run_now(admin: str = Depends(get_admin_user)):
    """스케줄에 관계없이 분석 파이프라인을 즉시 실행합니다."""
    try:
        from src.api.app_state import scheduler
        if scheduler is None:
            raise HTTPException(status_code=503, detail="스케줄러가 초기화되지 않았습니다")
        result = await scheduler.run_now()
        return {"message": "실행 완료", "result": result}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("즉시 실행 실패: %s", e)
        raise HTTPException(status_code=500, detail="서버 내부 오류가 발생했습니다")


@router.put("/scheduler/time", summary="스케줄 시각 변경")
async def update_scheduler_time(request: ScheduleUpdateRequest, admin: str = Depends(get_admin_user)):
    """자동 실행 시각을 변경합니다."""
    try:
        from src.api.app_state import scheduler
        if scheduler is None:
            raise HTTPException(status_code=503, detail="스케줄러가 초기화되지 않았습니다")
        scheduler.update_schedule(request.hour, request.minute)

        # settings.json에도 저장
        settings = _load_settings()
        settings["schedule_time"] = f"{request.hour:02d}:{request.minute:02d}"
        _save_settings(settings)

        return {
            "message": f"스케줄이 매일 {request.hour:02d}:{request.minute:02d}으로 변경되었습니다.",
            "schedule_time": f"{request.hour:02d}:{request.minute:02d}",
            "next_run_at": scheduler.next_run_at.isoformat() if scheduler.next_run_at else None,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("스케줄 변경 실패: %s", e)
        raise HTTPException(status_code=500, detail="서버 내부 오류가 발생했습니다")


@router.post("/scheduler/start", summary="스케줄러 시작")
async def start_scheduler(admin: str = Depends(get_admin_user)):
    """중지된 스케줄러를 다시 시작합니다."""
    try:
        from src.api.app_state import scheduler, scheduled_analysis_job
        if scheduler is None:
            raise HTTPException(status_code=503, detail="스케줄러가 초기화되지 않았습니다")
        if scheduler.is_running:
            return {"message": "스케줄러가 이미 실행 중입니다.", "status": scheduler.get_status()}
        scheduler.start(scheduled_analysis_job)
        return {"message": "스케줄러가 시작되었습니다.", "status": scheduler.get_status()}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("스케줄러 시작 실패: %s", e)
        raise HTTPException(status_code=500, detail="서버 내부 오류가 발생했습니다")


@router.post("/scheduler/stop", summary="스케줄러 중지")
async def stop_scheduler(admin: str = Depends(get_admin_user)):
    """자동 스케줄러를 중지합니다."""
    try:
        from src.api.app_state import scheduler
        if scheduler is None:
            raise HTTPException(status_code=503, detail="스케줄러가 초기화되지 않았습니다")
        scheduler.stop()
        return {"message": "스케줄러가 중지되었습니다.", "status": scheduler.get_status()}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("스케줄러 중지 실패: %s", e)
        raise HTTPException(status_code=500, detail="서버 내부 오류가 발생했습니다")


# ──────────────────────────────────────────────
# Slack API
# ──────────────────────────────────────────────


@router.post("/slack/test", summary="Slack 테스트 메시지")
async def test_slack(admin: str = Depends(get_admin_user)):
    """현재 설정된 Slack 웹훅으로 테스트 메시지를 전송합니다."""

    webhook_url = os.getenv("SLACK_WEBHOOK_URL", "")

    # settings.json에서도 확인
    settings = _load_settings()
    webhook_url = settings.get("slack_webhook_url", webhook_url)

    if not webhook_url:
        raise HTTPException(status_code=400, detail="SLACK_WEBHOOK_URL이 설정되지 않았습니다.")

    try:
        from src.reporters.slack_reporter import SlackReporter
        reporter = SlackReporter(webhook_url=webhook_url)
        success = reporter.send_alert(
            title="🔔 NARA Analyzer 연동 테스트",
            message="Slack 알림이 정상적으로 연동되었습니다! 🎉\n매일 아침 분석 결과가 이 채널로 전송됩니다.",
            level="info",
        )
        if success:
            return {"message": "테스트 메시지가 전송되었습니다."}
        else:
            raise HTTPException(status_code=500, detail="메시지 전송에 실패했습니다.")
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Slack 전송 실패: %s", e)
        raise HTTPException(status_code=500, detail="서버 내부 오류가 발생했습니다")


@router.put("/settings/slack", summary="Slack 웹훅 URL 설정")
async def update_slack_webhook(request: SlackWebhookRequest, admin: str = Depends(get_admin_user)):
    """Slack Incoming Webhook URL을 저장합니다."""
    try:
        settings = _load_settings()
        settings["slack_webhook_url"] = request.webhook_url
        _save_settings(settings)

        return {
            "message": "Slack 웹훅 URL이 저장되었습니다.",
            "configured": True,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Slack 설정 실패: %s", e)
        raise HTTPException(status_code=500, detail="서버 내부 오류가 발생했습니다")


@router.post("/settings/test-key", summary="API 키 연결 테스트 (Ping Test)")
async def test_api_key(request: ApiKeyTestRequest):
    """
    입력된 API 키의 유효성을 실시간으로 확인합니다.
    """
    name = request.api_name
    key = request.api_key
    secret = request.api_secret

    try:
        if name == "data_go_kr":
            url = f"https://apis.data.go.kr/1230000/BidPublicInfoService05/getBidPblancListInfoCnstcPPss?serviceKey={key}&numOfRows=1&pageNo=1&inqryDiv=1&type=json"
            async with httpx.AsyncClient(timeout=5.0) as client:
                res = await client.get(url)
                if res.status_code == 200:
                    content = res.text
                    if "SERVICE_KEY_IS_NOT_REGISTERED_ERROR" in content or "SERVICE KEY IS NOT REGISTERED" in content:
                        return {"success": False, "message": "등록되지 않은 서비스 키입니다. (인증 대기시간 확인 필요)"}
                    if "INVALID_REQUEST_PARAMETER_ERROR" in content:
                        return {"success": False, "message": "요청 파라미터가 유효하지 않습니다."}
                    return {"success": True, "message": "공공데이터포털 연결 성공!"}
                else:
                    return {"success": False, "message": f"연결 실패 (HTTP {res.status_code})"}

        elif name == "naver":
            if not secret:
                return {"success": False, "message": "Client Secret이 입력되지 않았습니다."}
            url = "https://openapi.naver.com/v1/search/news.json?query=테스트&display=1"
            headers = {
                "X-Naver-Client-Id": key,
                "X-Naver-Client-Secret": secret
            }
            async with httpx.AsyncClient(timeout=5.0) as client:
                res = await client.get(url, headers=headers)
                if res.status_code == 200:
                    return {"success": True, "message": "네이버 검색 API 연결 성공!"}
                else:
                    try:
                        err_msg = res.json().get("errorMessage", f"HTTP {res.status_code}")
                    except Exception:
                        err_msg = f"HTTP {res.status_code}"
                    return {"success": False, "message": f"네이버 연결 실패: {err_msg}"}

        elif name == "openai":
            url = "https://api.openai.com/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json"
            }
            payload = {
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 1
            }
            async with httpx.AsyncClient(timeout=5.0) as client:
                res = await client.post(url, headers=headers, json=payload)
                if res.status_code == 200:
                    return {"success": True, "message": "OpenAI API 연결 성공!"}
                else:
                    try:
                        err_msg = res.json().get("error", {}).get("message", f"HTTP {res.status_code}")
                    except Exception:
                        err_msg = f"HTTP {res.status_code}"
                    return {"success": False, "message": f"OpenAI 연결 실패: {err_msg}"}

        elif name == "gemini":
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={key}"
            payload = {
                "contents": [{"parts": [{"text": "ping"}]}]
            }
            async with httpx.AsyncClient(timeout=5.0) as client:
                res = await client.post(url, json=payload)
                if res.status_code == 200:
                    return {"success": True, "message": "Google Gemini API 연결 성공!"}
                else:
                    try:
                        err_msg = res.json().get("error", {}).get("message", f"HTTP {res.status_code}")
                    except Exception:
                        err_msg = f"HTTP {res.status_code}"
                    return {"success": False, "message": f"Gemini 연결 실패: {err_msg}"}

        elif name == "youtube":
            # YouTube Data API v3 연결 테스트
            url = f"https://www.googleapis.com/youtube/v3/search?part=snippet&q=test&maxResults=1&key={key}"
            async with httpx.AsyncClient(timeout=5.0) as client:
                res = await client.get(url)
                if res.status_code == 200:
                    return {"success": True, "message": "YouTube Data API 연결 성공!"}
                else:
                    try:
                        err_msg = res.json().get("error", {}).get("message", f"HTTP {res.status_code}")
                    except Exception:
                        err_msg = f"HTTP {res.status_code}"
                    return {"success": False, "message": f"YouTube 연결 실패: {err_msg}"}

        elif name == "kakao":
            # 카카오 지도 API 연결 테스트
            url = "https://dapi.kakao.com/v2/local/search/keyword.json?query=서울시청"
            headers = {"Authorization": f"KakaoAK {key}"}
            async with httpx.AsyncClient(timeout=5.0) as client:
                res = await client.get(url, headers=headers)
                if res.status_code == 200:
                    return {"success": True, "message": "카카오 지도 API 연결 성공!"}
                else:
                    return {"success": False, "message": f"카카오 연결 실패: HTTP {res.status_code}"}

        else:
            return {"success": False, "message": "알 수 없는 API 이름입니다."}

    except httpx.ConnectTimeout:
        return {"success": False, "message": "연결 타임아웃이 발생했습니다."}
    except Exception as e:
        logger.error("API 연결 테스트 실패: %s", e)
        return {"success": False, "message": f"오류 발생: {str(e)}"}


# ──────────────────────────────────────────────
# 개인화 AI 에이전트 설정 API
# ──────────────────────────────────────────────

@router.get("/user/ai-settings", summary="개인 AI 에이전트 설정 조회")
async def get_user_ai_settings(
    username: str = Depends(get_current_user),
    db: DatabaseManager = Depends(get_db)
):
    """
    현재 로그인된 사용자의 개인화 AI 에이전트 설정(가중치 슬라이더, 투찰Persona 등)을 가져옵니다.
    설정이 아직 없다면 디폴트 설정값을 반환합니다.
    """
    try:
        settings = db.get_user_ai_settings(username)
        if not settings:
            return {
                "username": username,
                "bid_target": "stable",
                "relevance_weight": 0.35,
                "capacity_weight": 0.35,
                "credit_weight": 0.30,
                "ai_persona": "strategic",
                "custom_keywords": []
            }
        return settings
    except Exception as e:
        logger.error("개인 AI 설정 조회 실패 [유저: %s]: %s", username, e)
        raise HTTPException(status_code=500, detail="개인 AI 설정을 조회하는 도중 오류가 발생했습니다.")


@router.post("/user/ai-settings", summary="개인 AI 에이전트 설정 업데이트")
async def update_user_ai_settings(
    req: AISettingsUpdateRequest,
    username: str = Depends(get_current_user),
    db: DatabaseManager = Depends(get_db)
):
    """
    사용자가 직접 조정한 개인 AI 가중치 및 입찰Persona 설정을 저장합니다.
    """
    try:
        total = req.relevance_weight + req.capacity_weight + req.credit_weight
        if abs(total - 1.0) > 0.01:
            if total == 0:
                req.relevance_weight = 0.35
                req.capacity_weight = 0.35
                req.credit_weight = 0.30
            else:
                req.relevance_weight = round(req.relevance_weight / total, 3)
                req.capacity_weight = round(req.capacity_weight / total, 3)
                req.credit_weight = round(req.credit_weight / total, 3)

        settings_dict = {
            "bid_target": req.bid_target,
            "relevance_weight": req.relevance_weight,
            "capacity_weight": req.capacity_weight,
            "credit_weight": req.credit_weight,
            "ai_persona": req.ai_persona,
            "custom_keywords": req.custom_keywords,
        }
        success = db.save_user_ai_settings(username, settings_dict)
        if not success:
            raise HTTPException(status_code=500, detail="AI 설정을 데이터베이스에 저장하지 못했습니다.")
        
        return {
            "message": "나의 AI 에이전트 설정이 업데이트되었습니다.",
            "settings": settings_dict
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("개인 AI 설정 저장 실패 [유저: %s]: %s", username, e)
        raise HTTPException(status_code=500, detail="설정 저장 중 서버 오류가 발생했습니다.")

