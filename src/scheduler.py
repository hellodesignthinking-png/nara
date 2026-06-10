"""
자동 스케줄러 모듈

asyncio 기반으로 매일 지정된 시각에 자동으로
공고 수집 → 분석 → 알림 파이프라인을 실행합니다.

외부 라이브러리(APScheduler 등)에 의존하지 않고,
Python 표준 라이브러리만으로 구현하여 경량화했습니다.

FastAPI lifespan에서 백그라운드 태스크로 실행됩니다.
"""

import asyncio
import logging
from datetime import datetime, timedelta, time as dt_time
from typing import Optional, Callable, Awaitable
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

# 한국 표준시 (KST)
_KST = ZoneInfo('Asia/Seoul')

# 연속 에러 최대 재시도 횟수
MAX_RETRIES = 10


class DailyScheduler:
    """
    매일 지정 시각에 작업을 실행하는 비동기 스케줄러

    Features:
      - 매일 지정 시각(기본 08:00)에 자동 실행
      - 수동 즉시 실행 API 제공
      - 상태 조회 (다음 실행 시각, 최근 실행 결과)
      - FastAPI 생명주기에 통합 (시작/종료 관리)
    """

    def __init__(
        self,
        run_hour: int = 8,
        run_minute: int = 0,
    ):
        """
        Args:
            run_hour: 실행 시각 (시, 0~23)
            run_minute: 실행 시각 (분, 0~59)
        """
        self.run_time = dt_time(run_hour, run_minute)
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._job_func: Optional[Callable[[], Awaitable[dict]]] = None

        # 상태 추적
        self.last_run_at: Optional[datetime] = None
        self.last_result: Optional[dict] = None
        self.last_error: Optional[str] = None
        self.total_runs: int = 0
        self.total_errors: int = 0
        self._consecutive_errors: int = 0

    @property
    def is_running(self) -> bool:
        """스케줄러가 실행 중인지 확인합니다."""
        return self._running and self._task is not None and not self._task.done()

    @property
    def next_run_at(self) -> Optional[datetime]:
        """다음 실행 예정 시각을 반환합니다."""
        if not self._running:
            return None
        now = datetime.now(tz=_KST)
        today_run = now.replace(
            hour=self.run_time.hour,
            minute=self.run_time.minute,
            second=0,
            microsecond=0,
        )
        if now >= today_run:
            return today_run + timedelta(days=1)
        return today_run

    # ══════════════════════════════════════════════
    # 생명주기 관리
    # ══════════════════════════════════════════════

    def start(self, job_func: Callable[[], Awaitable[dict]]) -> None:
        """
        스케줄러를 시작합니다.

        Args:
            job_func: 매일 실행할 비동기 함수. dict를 반환해야 합니다.
        """
        if self.is_running:
            logger.warning("스케줄러가 이미 실행 중입니다.")
            return

        self._job_func = job_func
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info(
            "⏰ 스케줄러 시작 — 매일 %02d:%02d에 실행됩니다. 다음 실행: %s",
            self.run_time.hour,
            self.run_time.minute,
            self.next_run_at,
        )

    def stop(self) -> None:
        """스케줄러를 중지합니다."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
        logger.info("⏹️ 스케줄러 중지됨")

    def update_schedule(self, hour: int, minute: int = 0) -> None:
        """
        실행 시각을 변경합니다.

        변경 후 다음 실행부터 새 시각이 적용됩니다.

        Args:
            hour: 새 실행 시각 (시, 0~23)
            minute: 새 실행 시각 (분, 0~59)
        """
        self.run_time = dt_time(hour, minute)
        logger.info("⏰ 스케줄 변경 → 매일 %02d:%02d", hour, minute)

    # ══════════════════════════════════════════════
    # 수동 실행
    # ══════════════════════════════════════════════

    async def run_now(self) -> dict:
        """
        스케줄에 관계없이 즉시 작업을 실행합니다.

        Returns:
            실행 결과 dict
        """
        if not self._job_func:
            return {"error": "실행할 작업이 등록되지 않았습니다."}

        logger.info("🚀 수동 실행 요청")
        return await self._execute_job()

    # ══════════════════════════════════════════════
    # 상태 조회
    # ══════════════════════════════════════════════

    def get_status(self) -> dict:
        """현재 스케줄러 상태를 반환합니다."""
        return {
            "is_running": self.is_running,
            "schedule_time": f"{self.run_time.hour:02d}:{self.run_time.minute:02d}",
            "next_run_at": self.next_run_at.isoformat() if self.next_run_at else None,
            "last_run_at": self.last_run_at.isoformat() if self.last_run_at else None,
            "last_result": self.last_result,
            "last_error": self.last_error,
            "total_runs": self.total_runs,
            "total_errors": self.total_errors,
        }

    # ══════════════════════════════════════════════
    # 내부 로직
    # ══════════════════════════════════════════════

    async def _loop(self) -> None:
        """메인 스케줄 루프. 매일 지정 시각까지 대기 후 실행합니다."""
        while self._running:
            try:
                # 다음 실행까지 대기 시간 계산
                wait_seconds = self._seconds_until_next_run()
                next_time = self.next_run_at

                logger.info(
                    "⏳ 다음 실행까지 %s (예정: %s)",
                    self._format_duration(wait_seconds),
                    next_time.strftime("%Y-%m-%d %H:%M") if next_time else "?",
                )

                # 대기
                await asyncio.sleep(wait_seconds)

                # 실행
                if self._running:
                    await self._execute_job()

            except asyncio.CancelledError:
                logger.info("스케줄러 루프 취소됨")
                break
            except Exception as e:
                self._consecutive_errors += 1
                logger.error(
                    "스케줄러 루프 에러 (%d/%d): %s",
                    self._consecutive_errors, MAX_RETRIES, e,
                )
                self.total_errors += 1
                self.last_error = str(e)

                if self._consecutive_errors >= MAX_RETRIES:
                    logger.error(
                        "❌ 연속 %d회 에러 발생 — 스케줄러를 중지합니다.",
                        MAX_RETRIES,
                    )
                    self._running = False
                    break

                # 에러 발생 시 지수 백오프 재시도 (최대 1시간)
                backoff = min(60 * (2 ** (self._consecutive_errors - 1)), 3600)
                logger.info("⏳ %d초 후 재시도 (%d번째 에러)", backoff, self._consecutive_errors)
                await asyncio.sleep(backoff)

    async def _execute_job(self) -> dict:
        """등록된 작업을 실행하고 결과를 기록합니다."""
        start_time = datetime.now(tz=_KST)
        logger.info("🔄 스케줄 작업 실행 시작 [%s]", start_time.strftime("%H:%M:%S"))

        try:
            result = await self._job_func()
            elapsed = (datetime.now(tz=_KST) - start_time).total_seconds()

            # 작업 성공 시 연속 에러 카운터 초기화
            self._consecutive_errors = 0

            self.last_run_at = start_time
            self.last_result = {
                **result,
                "elapsed_seconds": round(elapsed, 1),
                "executed_at": start_time.isoformat(),
            }
            self.last_error = None
            self.total_runs += 1

            logger.info(
                "✅ 스케줄 작업 완료 (%.1f초 소요): %s",
                elapsed,
                result,
            )
            return self.last_result

        except Exception as e:
            elapsed = (datetime.now(tz=_KST) - start_time).total_seconds()
            self.last_run_at = start_time
            self.last_error = str(e)
            self.total_errors += 1

            logger.error("❌ 스케줄 작업 실패 (%.1f초): %s", elapsed, e)
            return {
                "error": str(e),
                "elapsed_seconds": round(elapsed, 1),
                "executed_at": start_time.isoformat(),
            }

    def _seconds_until_next_run(self) -> float:
        """다음 실행 시각까지의 남은 초를 계산합니다."""
        now = datetime.now(tz=_KST)
        target = now.replace(
            hour=self.run_time.hour,
            minute=self.run_time.minute,
            second=0,
            microsecond=0,
        )
        if now >= target:
            target += timedelta(days=1)

        delta = (target - now).total_seconds()
        return max(delta, 1)  # 최소 1초

    @staticmethod
    def _format_duration(seconds: float) -> str:
        """초를 'Xh Xm' 형식으로 변환합니다."""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        if hours > 0:
            return f"{hours}시간 {minutes}분"
        return f"{minutes}분"
