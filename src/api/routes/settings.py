"""
설정 API 라우트

/settings/*, /scheduler/*, /slack/* 엔드포인트:
시스템 설정 조회/변경, 스케줄러 제어, Slack 연동
"""

import logging
import os
from pathlib import Path as _Path

from fastapi import APIRouter, Body, HTTPException

from src.config import load_config

from ._helpers import _load_settings, _save_settings
from ._models import (
    KeywordsUpdateRequest,
    RelevanceUpdateRequest,
    ScheduleUpdateRequest,
    SlackWebhookRequest,
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
async def update_api_keys(request: dict = Body(...)):
    """
    API 키를 업데이트합니다. .env 파일과 settings.json에 동시 저장합니다.

    지원 키:
    - data_go_kr_api_key: 공공데이터포털 API 키
    - naver_client_id: 네이버 Client ID
    - naver_client_secret: 네이버 Client Secret
    - openai_api_key: OpenAI API 키
    """
    try:
        env_path = _Path(__file__).resolve().parent.parent.parent.parent / ".env"
        env_map = {
            "data_go_kr_api_key": "DATA_GO_KR_API_KEY",
            "naver_client_id": "NAVER_CLIENT_ID",
            "naver_client_secret": "NAVER_CLIENT_SECRET",
            "openai_api_key": "OPENAI_API_KEY",
            "gemini_api_key": "GEMINI_API_KEY",
            "llm_engine": "LLM_ENGINE",
        }

        # .env 파일 읽기
        env_lines = []
        if env_path.exists():
            env_lines = env_path.read_text(encoding="utf-8").splitlines()

        updated_keys = []
        for field, env_var in env_map.items():
            value = request.get(field)
            if value is None:
                continue
            value = value.strip()

            # .env 업데이트
            found = False
            for i, line in enumerate(env_lines):
                if line.startswith(f"{env_var}=") or line.startswith(f"# {env_var}="):
                    env_lines[i] = f"{env_var}={value}"
                    found = True
                    break
            if not found:
                env_lines.append(f"{env_var}={value}")

            # 환경변수도 즉시 반영

            os.environ[env_var] = value
            updated_keys.append(field)

        # .env 저장
        env_path.write_text("\n".join(env_lines) + "\n", encoding="utf-8")

        # Config 캐시 무효화 — 다음 load_config() 호출 시 새로운 환경변수 반영
        try:
            import src.config as _cfg_module
            _cfg_module._config_instance = None
        except Exception:
            pass

        logger.info("API 키 업데이트: %s", updated_keys)
        return {
            "message": f"API 키가 업데이트되었습니다: {', '.join(updated_keys)}",
            "updated": updated_keys,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("API 키 업데이트 실패: %s", e)
        raise HTTPException(status_code=500, detail="서버 내부 오류가 발생했습니다")


@router.get("/settings/api-keys", summary="API 키 상태 조회 (마스킹)")
async def get_api_keys_masked():
    """API 키 설정 여부와 마스킹된 값을 반환합니다."""
    try:
        config = load_config()

        def mask(val):
            if not val:
                return ""
            if len(val) <= 8:
                return "****"
            return val[:4] + "*" * (len(val) - 8) + val[-4:]

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
                "set": bool(config.openai_api_key),
                "masked": mask(config.openai_api_key),
            },
            "gemini_api_key": {
                "set": bool(getattr(config, 'gemini_api_key', '')),
                "masked": mask(getattr(config, 'gemini_api_key', '')),
            },
            "llm_engine": {
                "set": True,
                "masked": getattr(config, 'llm_engine', 'openai'),
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
async def scheduler_run_now():
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
async def update_scheduler_time(request: ScheduleUpdateRequest):
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
async def start_scheduler():
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
async def stop_scheduler():
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
async def test_slack():
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
async def update_slack_webhook(request: SlackWebhookRequest):
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
