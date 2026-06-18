"""
FastAPI 메인 애플리케이션 모듈

나라장터 자동 분석 시스템의 웹 API 서버를 구성합니다.

기능:
  - /api/* : REST API 엔드포인트 (routes.py에서 정의)
  - /       : 프론트엔드 SPA (static/index.html)
  - static/ : 정적 파일 서빙 (HTML, CSS, JS)
  - 스케줄러: 매일 자동 분석 실행
  - Slack: 분석 결과 알림

실행:
    python -m src.api.app
    또는
    uvicorn src.api.app:app --reload --port 8000
"""

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from src.config import load_config, PROJECT_ROOT
from src.models.database import DatabaseManager
from src.api.routes import create_main_router
from src.scheduler import DailyScheduler
from src.api import app_state
from src.api.routes._helpers import _load_settings

__version__ = "1.1.0"

# 로깅 설정 (구조화 로깅 모듈 사용)
try:
    from src.utils.logging_config import setup_logging
    setup_logging()
except Exception:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
logger = logging.getLogger("nara.api")

# 정적 파일 디렉터리 경로 (모듈 로드 시점에 생성하여 mount 등록 보장)
STATIC_DIR = PROJECT_ROOT / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)

# 전역 스케줄러 참조 (app_state 모듈에서 관리)
# 하위호환을 위해 모듈 레벨 변수도 유지
scheduler = None


# ──────────────────────────────────────────────
# 스케줄 작업 정의
# ──────────────────────────────────────────────

async def scheduled_analysis_job() -> dict:
    """
    매일 자동 실행되는 분석 파이프라인 (공유 캐시 채우기 포함)

    1. 오늘 전체 공고 수집 → 공유 DB 캐시에 저장 (모든 사용자 혜택)
    2. 저장된 관심 키워드로 추가 수집
    3. Slack 알림 전송

    Returns:
        실행 결과 요약 dict
    """
    import asyncio
    from src.collectors.bid_collector import BidCollector
    from src.collectors.universal_collector import UniversalBidCollector
    from src.reporters.slack_reporter import SlackReporter
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    config = load_config()
    result_summary = {
        "collected": 0,
        "saved": 0,
        "keyword_collected": 0,
        "analyzed": 0,
        "notified": False,
    }

    user_settings = _load_settings()
    saved_keywords = user_settings.get("keywords") or config.keywords or []
    exclude_keywords = user_settings.get("exclude_keywords") or []

    kst_now = datetime.now(tz=ZoneInfo("Asia/Seoul"))
    today_str = kst_now.strftime("%Y-%m-%d")
    logger.info("🌅 아침 자동 수집 시작 [%s] — 공유 캐시 갱신", today_str)

    all_bids = []
    seen_nos = set()

    # ── 1단계: 최근 3일 전체 공고 광범위 수집 (공유 캐시용) ──────────────
    #    Render 무료 플랜은 스핀다운으로 스케줄을 놓칠 수 있으므로
    #    최근 3일 수집으로 누락 방지
    try:
        collector = UniversalBidCollector(config)
        from datetime import timedelta as td
        start_3d = (kst_now - td(days=2)).strftime("%Y%m%d")
        end_today = kst_now.strftime("%Y%m%d")

        logger.info("📥 최근 3일 전체 공고 수집 중 (%s ~ %s)...", start_3d, end_today)
        today_bids = await asyncio.to_thread(
            collector.collect_all_sources, start_3d, end_today, []
        )
        for b in today_bids:
            if b.bid_ntce_no not in seen_nos:
                seen_nos.add(b.bid_ntce_no)
                all_bids.append(b)

        logger.info("📋 최근 3일 전체 공고 수집: %d건 (중복 제거 후 %d건)", len(today_bids), len(all_bids))
        result_summary["collected"] = len(all_bids)

    except Exception as e:
        logger.warning("전체 공고 수집 실패 (키워드 수집으로 계속): %s", e)
        result_summary["collect_all_error"] = str(e)

    # ── 2단계: 관심 키워드 기반 추가 수집 ───────────────────────────
    try:
        kw_collector = BidCollector(config)

        if saved_keywords:
            for kw in saved_keywords:
                try:
                    kw_bids = await asyncio.to_thread(
                        kw_collector.collect_bids_by_keyword, kw, 7
                    )
                    added = 0
                    for b in kw_bids:
                        if b.bid_ntce_no not in seen_nos:
                            seen_nos.add(b.bid_ntce_no)
                            all_bids.append(b)
                            added += 1
                    logger.info("🔍 키워드 '%s' → %d건 (신규 %d건)", kw, len(kw_bids), added)
                    result_summary["keyword_collected"] += len(kw_bids)
                except Exception as kw_err:
                    logger.warning("키워드 '%s' 수집 실패: %s", kw, kw_err)

    except Exception as e:
        logger.error("키워드 수집 실패: %s", e)
        result_summary["keyword_error"] = str(e)

    # ── 3단계: 제외 키워드 필터링 ─────────────────────────────────────
    if exclude_keywords:
        before = len(all_bids)
        all_bids = [
            b for b in all_bids
            if not any(ek.lower() in (b.title or '').lower() for ek in exclude_keywords)
        ]
        logger.info("🚫 제외 키워드 필터: %d건 → %d건", before, len(all_bids))

    # ── 4단계: DB에 저장 (공유 캐시) ──────────────────────────────────
    try:
        # app_state에서 공유 DB 사용
        from src.api import app_state
        if app_state.db:
            saved_count = app_state.db.save_bids(all_bids)
        else:
            db = DatabaseManager(config.db_path)
            db.connect()
            try:
                saved_count = db.save_bids(all_bids)
            finally:
                db.close()

        result_summary["saved"] = saved_count
        logger.info(
            "✅ 아침 수집 완료: 전체 %d건 수집, %d건 신규 저장 (공유 캐시 갱신)",
            len(all_bids), saved_count
        )
    except Exception as e:
        logger.error("DB 저장 실패: %s", e)
        result_summary["save_error"] = str(e)

    # ── 5단계: Slack 알림 ─────────────────────────────────────────────
    try:
        slack_url = os.getenv("SLACK_WEBHOOK_URL", "")
        slack_url = user_settings.get("slack_webhook_url", "") or slack_url

        if slack_url and len(all_bids) > 0:
            slack = SlackReporter(webhook_url=slack_url)
            slack.send_alert(
                title="🌅 나라장터 오늘 공고 수집 완료",
                message=(
                    f"📋 총 {len(all_bids)}건 수집, {result_summary.get('saved', 0)}건 신규 저장\n"
                    f"🔍 키워드 수집: {result_summary.get('keyword_collected', 0)}건\n"
                    f"📅 수집일: {today_str}"
                ),
            )
            result_summary["notified"] = True
            logger.info("📨 Slack 알림 전송 완료")
    except Exception as e:
        logger.warning("Slack 알림 실패: %s", e)
        result_summary["notify_error"] = str(e)

    return result_summary


# ──────────────────────────────────────────────
# 앱 생명주기 관리 (lifespan)
# ──────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    앱 시작/종료 시 실행되는 생명주기 핸들러

    시작 시:
      - 설정 로드 및 검증
      - 데이터베이스 테이블 초기화
      - 정적 파일 디렉터리 생성
      - 자동 스케줄러 시작

    종료 시:
      - 스케줄러 중지
      - 리소스 정리
    """
    # ── 앱 시작 ──
    logger.info("🚀 NARA Analyzer API 서버 시작 중...")

    # 설정 로드 및 검증
    config = load_config()
    warnings = config.validate()
    for w in warnings:
        logger.warning("⚠️ %s", w)

    # 데이터베이스 초기화 (테이블 생성, 손상 시 복구)
    try:
        db = DatabaseManager(config.db_path)
        db.connect()
        db.init_db()
        db.close()
        logger.info("✅ 데이터베이스 초기화 완료: %s", config.db_path)
    except Exception as db_err:
        logger.error("❌ 데이터베이스 초기화 실패: %s", db_err)
        # DB 파일 백업 후 새로 생성 시도
        import shutil
        db_path = Path(config.db_path)
        if db_path.exists():
            backup_path = db_path.with_suffix(".db.corrupted")
            shutil.move(str(db_path), str(backup_path))
            logger.warning("🔄 손상된 DB를 %s로 백업하고 새 DB 생성", backup_path)
        db = DatabaseManager(config.db_path)
        db.connect()
        db.init_db()
        db.close()
        logger.info("✅ 새 데이터베이스 생성 완료")

    # 정적 파일 디렉터리 보장
    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    logger.info("✅ 정적 파일 디렉터리: %s", STATIC_DIR)

    # 스케줄러 시작 (환경변수로 시각 설정 가능)
    global scheduler
    try:
        sched_hour = int(os.getenv("SCHEDULE_HOUR", "8"))
        sched_min = int(os.getenv("SCHEDULE_MINUTE", "0"))
    except ValueError:
        logger.warning("SCHEDULE_HOUR/MINUTE 환경변수가 잘못된 형식입니다. 기본값 08:00 사용")
        sched_hour, sched_min = 8, 0
    sched_enabled = os.getenv("SCHEDULER_ENABLED", "true").lower() in ("true", "1", "yes")

    # settings.json에서 스케줄 시간 우선 적용
    try:
        user_settings = _load_settings()
        schedule_time_str = user_settings.get("schedule_time", "")
        if schedule_time_str and ":" in schedule_time_str:
            parts = schedule_time_str.split(":")
            sched_hour = int(parts[0])
            sched_min = int(parts[1])
    except Exception:
        pass  # settings.json 읽기 실패 시 환경변수 값 유지

    if sched_enabled:
        scheduler = DailyScheduler(run_hour=sched_hour, run_minute=sched_min)
        scheduler.start(scheduled_analysis_job)
        # app_state에도 등록 (순환 import 방지)
        app_state.scheduler = scheduler
        app_state.scheduled_analysis_job = scheduled_analysis_job
        logger.info("✅ 자동 스케줄러 활성화: 매일 %02d:%02d", sched_hour, sched_min)
    else:
        logger.info("ℹ️ 자동 스케줄러 비활성화 (SCHEDULER_ENABLED=false)")

    logger.info("✅ NARA Analyzer API 서버 준비 완료")

    yield  # 앱 실행 중

    # ── 앱 종료 ──
    if scheduler is not None:
        scheduler.stop()
        app_state.scheduler = None
    logger.info("🛑 NARA Analyzer API 서버 종료")


# ──────────────────────────────────────────────
# FastAPI 앱 생성
# ──────────────────────────────────────────────

app = FastAPI(
    title="NARA Analyzer",
    description="나라장터 용역 자동 분석 시스템 API",
    version=__version__,
    lifespan=lifespan,
)

# ──────────────────────────────────────────────
# CORS 미들웨어 설정
# 프론트엔드 개발 서버(예: localhost:3000)에서의
# 교차 출처 요청을 허용합니다.
# ──────────────────────────────────────────────

CORS_ORIGINS_RAW = os.getenv("CORS_ORIGINS", "http://localhost:8000,http://localhost:3000")
# '*' 로 설정하면 모든 오리진 허용 (Render 대시보드에서 CORS_ORIGINS=* 설정 시)
if CORS_ORIGINS_RAW.strip() == "*":
    ALLOWED_ORIGINS = ["*"]
else:
    ALLOWED_ORIGINS = [o.strip() for o in CORS_ORIGINS_RAW.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    # Render.com, trycloudflare.com, loca.lt 등 클라우드 도메인 자동 허용
    allow_origin_regex=r"https://(.*\.onrender\.com|.*\.trycloudflare\.com|.*\.loca\.lt|.*\.fly\.dev)",
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-API-Key", "Authorization", "X-Active-Company"],
)

# API Key 인증 미들웨어
# from src.api.middleware.auth import APIKeyAuthMiddleware
# app.add_middleware(APIKeyAuthMiddleware)

# ──────────────────────────────────────────────
# 헬스체크 엔드포인트
# ──────────────────────────────────────────────


@app.get("/health", tags=["system"])
async def health_check():
    """시스템 상태를 확인합니다."""
    sched = app_state.scheduler
    return {
        "status": "healthy",
        "scheduler_running": sched is not None and getattr(sched, 'is_running', False),
        "version": __version__,
    }


# ──────────────────────────────────────────────
# API 라우터 등록
# ──────────────────────────────────────────────

app.include_router(create_main_router())

# ──────────────────────────────────────────────
# 정적 파일 서빙
# /static/* 경로로 static/ 디렉터리의 파일에 접근
# ──────────────────────────────────────────────

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ──────────────────────────────────────────────
# 프론트엔드 SPA 라우트
# / 경로로 접속하면 static/index.html을 반환합니다.
# ──────────────────────────────────────────────


@app.get("/", include_in_schema=False)
async def serve_index():
    """루트 경로 접속 시 프론트엔드 index.html을 반환합니다."""
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))
    # index.html이 없으면 API 상태 정보를 반환
    return {
        "service": "NARA Analyzer API",
        "version": __version__,
        "status": "running",
        "docs": "/docs",
        "message": "static/index.html을 생성하면 프론트엔드를 서빙합니다.",
    }


# ──────────────────────────────────────────────
# 직접 실행 엔트리포인트
# python -m src.api.app 으로 실행 시 uvicorn 서버를 시작합니다.
# ──────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    dev_mode = os.getenv("DEV_MODE", "").lower() in ("true", "1", "yes")

    uvicorn.run(
        "src.api.app:app",
        host="0.0.0.0",
        port=8000,
        reload=dev_mode,
        reload_dirs=[str(PROJECT_ROOT / "src")] if dev_mode else None,
    )
