"""
Slack 웹훅 기반 알림 리포터

분석 결과를 Slack 채널로 전송합니다.
Block Kit 형식의 리치 메시지로 가독성을 높였습니다.

사용법:
    1. Slack App → Incoming Webhooks 활성화
    2. 채널에 웹훅 URL 생성
    3. .env에 SLACK_WEBHOOK_URL 추가
"""

import json
import logging
import re
from datetime import datetime
from typing import Any

from src.utils.formatters import format_budget
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

logger = logging.getLogger(__name__)

# Slack 웹훅 URL 정규식 패턴 (보안: 공식 도메인만 허용)
_SLACK_WEBHOOK_PATTERN = re.compile(
    r'^https://hooks\.slack\.com/services/T[A-Z0-9]+/B[A-Z0-9]+/[A-Za-z0-9]+$'
)


class SlackReporter:
    """
    Slack 웹훅 기반 리포터

    Incoming Webhook URL을 사용하여
    분석 결과를 Slack 채널에 자동 전송합니다.
    """

    def __init__(self, webhook_url: str = ""):
        """
        Args:
            webhook_url: Slack Incoming Webhook URL
        """
        self.webhook_url = webhook_url

    @property
    def is_configured(self) -> bool:
        """Slack 알림이 설정되었는지 확인합니다."""
        if not self.webhook_url:
            return False
        if not _SLACK_WEBHOOK_PATTERN.match(self.webhook_url):
            logger.warning(
                "Slack 웹훅 URL이 올바른 형식이 아닙니다. "
                "https://hooks.slack.com/services/... 형식이어야 합니다."
            )
            return False
        return True

    # ══════════════════════════════════════════════
    # 공개 API
    # ══════════════════════════════════════════════

    def send_daily_report(self, results: list[dict]) -> bool:
        """
        일일 분석 보고서를 Slack으로 전송합니다.

        Args:
            results: 분석 결과 리스트

        Returns:
            전송 성공 여부
        """
        if not self.is_configured:
            logger.warning("Slack 웹훅 URL이 설정되지 않았습니다.")
            return False

        blocks = self._build_report_blocks(results)
        return self._send_message(blocks)

    def send_alert(self, title: str, message: str, level: str = "info") -> bool:
        """
        단순 알림을 Slack으로 전송합니다.

        Args:
            title: 알림 제목
            message: 알림 내용
            level: 'info' | 'warning' | 'error'

        Returns:
            전송 성공 여부
        """
        if not self.is_configured:
            logger.warning("Slack 웹훅 URL이 설정되지 않았습니다.")
            return False

        icons = {"info": "ℹ️", "warning": "⚠️", "error": "🚨"}
        icon = icons.get(level, "ℹ️")

        blocks = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": f"{icon} {title}", "emoji": True},
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": message},
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} · NARA Analyzer",
                    }
                ],
            },
        ]
        return self._send_message(blocks)

    def send_bid_alert(self, bid: dict, relevance_score: float = 0) -> bool:
        """
        새 공고 알림을 Slack으로 전송합니다.

        Args:
            bid: 공고 정보 dict
            relevance_score: 관련도 점수

        Returns:
            전송 성공 여부
        """
        if not self.is_configured:
            return False

        title = bid.get("title", bid.get("bidNtceNm", "제목 없음"))
        org = bid.get("organization", bid.get("ntceInsttNm", ""))
        budget = self._format_budget(bid.get("budget", bid.get("presmptPrce", "")))
        deadline = str(bid.get("deadline", bid.get("bidClseDt", "")))[:16]

        emoji = "🟢" if relevance_score >= 70 else ("🟡" if relevance_score >= 40 else "🔴")

        blocks = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": "📋 새 공고 알림", "emoji": True},
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"*{title}*\n"
                        f"🏢 {org}\n"
                        f"💰 {budget} · 📅 마감: {deadline}\n"
                        f"{emoji} 관련도: *{relevance_score:.0f}점*"
                    ),
                },
            },
            {"type": "divider"},
        ]
        return self._send_message(blocks)

    # ══════════════════════════════════════════════
    # 보고서 빌더
    # ══════════════════════════════════════════════

    def _build_report_blocks(self, results: list[dict]) -> list[dict]:
        """분석 결과를 Block Kit 형식으로 변환합니다."""
        now = datetime.now()
        total = len(results)

        # 점수별 분류
        high = sum(1 for r in results if (r.get("match_score", 0) or r.get("relevance_score", 0)) >= 70)
        mid = sum(1 for r in results if 40 <= (r.get("match_score", 0) or r.get("relevance_score", 0)) < 70)
        low = total - high - mid

        blocks = [
            # 헤더
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"🏛️ NARA Analyzer 일일 분석 보고서",
                    "emoji": True,
                },
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"📅 {now.strftime('%Y년 %m월 %d일')} · 총 *{total}건* 분석 완료",
                    }
                ],
            },
            # 요약 통계
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"🟢 *적극 권장*\n{high}건"},
                    {"type": "mrkdwn", "text": f"🟡 *검토 대상*\n{mid}건"},
                    {"type": "mrkdwn", "text": f"🔴 *참여 부적합*\n{low}건"},
                    {"type": "mrkdwn", "text": f"📊 *전체*\n{total}건"},
                ],
            },
            {"type": "divider"},
        ]

        # 상위 5건만 상세 표시
        for i, result in enumerate(results[:5], 1):
            bid = result.get("bid", result.get("bid_info", result))
            strategy = result.get("strategy", result)

            title = bid.get("title", bid.get("bidNtceNm", bid.get("bid_title", "제목 없음")))
            org = bid.get("organization", bid.get("ntceInsttNm", bid.get("org_name", "")))
            budget = self._format_budget(bid.get("budget", bid.get("presmptPrce", "")))

            score = result.get("match_score", result.get("relevance_score", 0))
            emoji = "🟢" if score >= 70 else ("🟡" if score >= 40 else "🔴")

            recommendation = strategy.get("overall_recommendation", "")
            if len(recommendation) > 150:
                recommendation = recommendation[:147] + "..."

            text = f"*{i}. {title}*\n🏢 {org} · 💰 {budget}\n{emoji} 점수: *{score:.0f}점*"
            if recommendation:
                text += f"\n🎯 _{recommendation}_"

            blocks.append(
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": text},
                }
            )

        if total > 5:
            blocks.append(
                {
                    "type": "context",
                    "elements": [
                        {"type": "mrkdwn", "text": f"_...외 {total - 5}건은 웹 대시보드에서 확인하세요._"}
                    ],
                }
            )

        # 푸터
        blocks.extend([
            {"type": "divider"},
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": (
                            f"🤖 자동 생성 · {now.strftime('%H:%M:%S')} · "
                            "AI 분석 결과는 참고용이며 공고 원문을 확인하세요."
                        ),
                    }
                ],
            },
        ])

        return blocks

    # ══════════════════════════════════════════════
    # HTTP 전송
    # ══════════════════════════════════════════════

    def _send_message(self, blocks: list[dict]) -> bool:
        """
        Block Kit 메시지를 Slack 웹훅으로 전송합니다.

        urllib만 사용하여 외부 의존성 없이 동작합니다.
        """
        payload = json.dumps({"blocks": blocks}).encode("utf-8")

        req = Request(
            self.webhook_url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urlopen(req, timeout=10) as response:
                if response.status == 200:
                    logger.info("Slack 메시지 전송 성공")
                    return True
                else:
                    logger.warning("Slack 응답 코드: %s", response.status)
                    return False
        except HTTPError as e:
            logger.error("Slack 전송 실패 (HTTP %s): %s", e.code, e.read().decode())
            return False
        except URLError as e:
            logger.error("Slack 전송 실패 (URL 에러): %s", e.reason)
            return False
        except Exception as e:
            logger.error("Slack 전송 실패: %s", e)
            return False

    # ══════════════════════════════════════════════
    # 유틸리티
    # ══════════════════════════════════════════════

    @staticmethod
    def _format_budget(budget: Any) -> str:
        """예산을 가독성 좋은 형식으로 포맷합니다."""
        return format_budget(budget, unit="원")
