"""
이메일 보고서 전송 모듈

Jinja2 HTML 템플릿 기반으로 분석 결과를 이메일로 전송합니다.
반응형 HTML 디자인으로 모바일에서도 최적화된 보고서를 제공합니다.
"""

import logging
import smtplib
import ssl
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Any
from zoneinfo import ZoneInfo

from src.utils.formatters import format_budget

from jinja2 import Environment, select_autoescape

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════
# 인라인 HTML 이메일 템플릿
# 반응형 디자인, 인라인 CSS, 모바일 최적화
# ══════════════════════════════════════════════════

EMAIL_TEMPLATE = """
<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>NARA Analyzer 일일 분석 보고서</title>
    <style>
        /* 기본 리셋 및 반응형 */
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', '맑은 고딕', 'Malgun Gothic', sans-serif;
            background-color: #f5f7fa;
            color: #333;
            line-height: 1.6;
            -webkit-text-size-adjust: 100%;
        }
        .container {
            max-width: 680px;
            margin: 0 auto;
            background: #ffffff;
        }

        /* 헤더 */
        .header {
            background: linear-gradient(135deg, #1a237e 0%, #0277bd 50%, #00838f 100%);
            color: white;
            padding: 32px 24px;
            text-align: center;
        }
        .header h1 {
            font-size: 24px;
            font-weight: 700;
            margin-bottom: 8px;
            letter-spacing: 1px;
        }
        .header .subtitle {
            font-size: 14px;
            opacity: 0.85;
        }
        .header .date {
            font-size: 13px;
            opacity: 0.7;
            margin-top: 8px;
        }

        /* 요약 통계 */
        .stats {
            display: flex;
            background: #e8eaf6;
            padding: 16px;
            justify-content: space-around;
            flex-wrap: wrap;
        }
        .stat-item {
            text-align: center;
            padding: 8px 16px;
        }
        .stat-item .number {
            font-size: 28px;
            font-weight: 700;
            color: #1a237e;
        }
        .stat-item .label {
            font-size: 12px;
            color: #666;
            margin-top: 2px;
        }

        /* 공고 카드 */
        .bid-card {
            border: 1px solid #e0e0e0;
            border-radius: 8px;
            margin: 16px;
            overflow: hidden;
        }
        .bid-card-header {
            padding: 16px;
            border-bottom: 1px solid #e0e0e0;
        }
        .bid-card-header h3 {
            font-size: 16px;
            color: #1a237e;
            margin-bottom: 4px;
        }
        .bid-card-header .org {
            font-size: 13px;
            color: #666;
        }
        .bid-card-body {
            padding: 16px;
        }
        .bid-meta {
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
            margin-bottom: 12px;
        }
        .bid-meta-item {
            background: #f5f5f5;
            border-radius: 4px;
            padding: 4px 10px;
            font-size: 12px;
            color: #555;
        }
        .bid-meta-item strong {
            color: #333;
        }

        /* 점수 뱃지 */
        .score-badge {
            display: inline-block;
            padding: 4px 12px;
            border-radius: 12px;
            font-size: 13px;
            font-weight: 600;
            color: white;
        }
        .score-high { background: #2e7d32; }
        .score-mid { background: #f57f17; }
        .score-low { background: #c62828; }

        /* 전략 섹션 */
        .strategy-section {
            margin-top: 12px;
            padding: 12px;
            background: #fafafa;
            border-radius: 6px;
            border-left: 3px solid #1a237e;
        }
        .strategy-section h4 {
            font-size: 14px;
            color: #1a237e;
            margin-bottom: 6px;
        }
        .strategy-section p,
        .strategy-section li {
            font-size: 13px;
            color: #444;
        }
        .strategy-section ul {
            padding-left: 20px;
            margin-top: 4px;
        }
        .strategy-section li {
            margin-bottom: 4px;
        }

        /* 매칭 정보 */
        .match-info {
            margin-top: 12px;
            padding: 10px 12px;
            background: #e8f5e9;
            border-radius: 6px;
        }
        .match-info .match-title {
            font-size: 13px;
            font-weight: 600;
            color: #2e7d32;
            margin-bottom: 4px;
        }
        .match-info .match-detail {
            font-size: 12px;
            color: #555;
        }

        /* 푸터 */
        .footer {
            background: #263238;
            color: #b0bec5;
            padding: 20px 24px;
            text-align: center;
            font-size: 12px;
        }
        .footer a {
            color: #80cbc4;
            text-decoration: none;
        }

        /* 구분선 */
        .divider {
            height: 1px;
            background: #e0e0e0;
            margin: 0 16px;
        }

        /* 반응형 미디어 쿼리 */
        @media only screen and (max-width: 600px) {
            .header h1 { font-size: 20px; }
            .stats { flex-direction: column; align-items: center; }
            .stat-item { margin-bottom: 8px; }
            .bid-card { margin: 8px; }
            .bid-meta { flex-direction: column; }
        }
    </style>
</head>
<body>
    <div class="container">
        <!-- 헤더 -->
        <div class="header">
            <h1>🏛️ NARA Analyzer</h1>
            <div class="subtitle">나라장터 용역 자동 분석 보고서</div>
            <div class="date">📅 {{ report_date }}</div>
        </div>

        <!-- 요약 통계 -->
        <div class="stats">
            <div class="stat-item">
                <div class="number">{{ total_count }}</div>
                <div class="label">분석 공고 수</div>
            </div>
            <div class="stat-item">
                <div class="number" style="color: #2e7d32;">{{ high_count }}</div>
                <div class="label">🟢 적극 권장</div>
            </div>
            <div class="stat-item">
                <div class="number" style="color: #f57f17;">{{ mid_count }}</div>
                <div class="label">🟡 검토 대상</div>
            </div>
            <div class="stat-item">
                <div class="number" style="color: #c62828;">{{ low_count }}</div>
                <div class="label">🔴 참여 부적합</div>
            </div>
        </div>

        <!-- 공고 카드 목록 -->
        {% for item in results %}
        <div class="bid-card">
            <div class="bid-card-header">
                <h3>{{ item.rank }}. {{ item.title }}</h3>
                <div class="org">🏢 {{ item.organization }}</div>
            </div>
            <div class="bid-card-body">
                <!-- 메타 정보 -->
                <div class="bid-meta">
                    <span class="bid-meta-item">
                        💰 <strong>예산</strong> {{ item.budget }}
                    </span>
                    <span class="bid-meta-item">
                        📅 <strong>마감</strong> {{ item.deadline }}
                    </span>
                    {% if item.relevance_score %}
                    <span class="score-badge {{ item.relevance_class }}">
                        관련도 {{ item.relevance_score }}점
                    </span>
                    {% endif %}
                </div>

                <!-- 매칭 사업자 -->
                {% if item.match_business %}
                <div class="match-info">
                    <div class="match-title">
                        🏢 최적 매칭: {{ item.match_business }}
                        <span class="score-badge {{ item.match_class }}">
                            {{ item.match_score }}점
                        </span>
                    </div>
                    <div class="match-detail">{{ item.match_recommendation }}</div>
                </div>
                {% endif %}

                <!-- 전략 요약 -->
                {% if item.bid_summary %}
                <div class="strategy-section">
                    <h4>📊 사업 분석</h4>
                    <p>{{ item.bid_summary }}</p>
                </div>
                {% endif %}

                {% if item.action_items %}
                <div class="strategy-section" style="border-left-color: #2e7d32;">
                    <h4>✅ 주요 체크리스트</h4>
                    <ul>
                    {% for action in item.action_items[:5] %}
                        <li>{{ action }}</li>
                    {% endfor %}
                    </ul>
                </div>
                {% endif %}

                {% if item.overall_recommendation %}
                <div class="strategy-section" style="border-left-color: #e65100;">
                    <h4>🎯 종합 권고</h4>
                    <p><strong>{{ item.overall_recommendation }}</strong></p>
                </div>
                {% endif %}
            </div>
        </div>

        {% if not loop.last %}
        <div class="divider"></div>
        {% endif %}
        {% endfor %}

        <!-- 푸터 -->
        <div class="footer">
            <p>이 보고서는 NARA Analyzer에 의해 자동 생성되었습니다.</p>
            <p style="margin-top: 8px;">생성 시각: {{ generated_at }}</p>
            <p style="margin-top: 4px; font-size: 11px;">
                AI 분석 결과는 참고용이며, 최종 입찰 결정은 공고 원문을 기준으로 판단하세요.
            </p>
        </div>
    </div>
</body>
</html>
"""


class EmailReporter:
    """
    Jinja2 HTML 템플릿 기반 이메일 보고서 전송기

    SMTP를 통해 분석 결과를 HTML 이메일로 전송합니다.
    반응형 디자인으로 PC/모바일 모두 최적화된 보고서를 제공합니다.
    """

    def __init__(
        self,
        smtp_host: str = 'smtp.gmail.com',
        smtp_port: int = 587,
        smtp_user: str = '',
        smtp_password: str = '',
    ):
        """
        이메일 보고서 전송기를 초기화합니다.

        Args:
            smtp_host: SMTP 서버 호스트
            smtp_port: SMTP 서버 포트
            smtp_user: SMTP 인증 사용자
            smtp_password: SMTP 인증 비밀번호
        """
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.smtp_user = smtp_user
        self.smtp_password = smtp_password

        # SMTP 비밀번호 마스킹 로깅 (보안: 자격 증명 노출 방지)
        masked_pw = '****' if smtp_password else '(미설정)'
        logger.debug(
            "EmailReporter 초기화: host=%s, port=%d, user=%s, password=%s",
            smtp_host, smtp_port, smtp_user, masked_pw,
        )

        # Jinja2 템플릿 컴파일 (보안: autoescape로 XSS 방지)
        self._env = Environment(autoescape=select_autoescape(['html', 'xml']))
        self._template = self._env.from_string(EMAIL_TEMPLATE)

    @property
    def is_configured(self) -> bool:
        """이메일 전송이 설정되었는지 확인합니다."""
        return bool(self.smtp_user and self.smtp_password)

    # ══════════════════════════════════════════════
    # 공개 API
    # ══════════════════════════════════════════════

    def send_daily_report(
        self,
        results: list[dict],
        recipients: list[str],
        subject: str | None = None,
    ) -> bool:
        """
        일일 분석 보고서를 이메일로 전송합니다.

        Args:
            results: 분석 결과 리스트
            recipients: 수신자 이메일 주소 목록
            subject: 이메일 제목 (미지정 시 자동 생성)

        Returns:
            전송 성공 여부
        """
        if not self.is_configured:
            logger.warning("SMTP 인증 정보가 설정되지 않아 이메일을 전송할 수 없습니다.")
            return False

        if not recipients:
            logger.warning("수신자가 지정되지 않았습니다.")
            return False

        # 이메일 제목 생성
        if not subject:
            today = datetime.now(tz=ZoneInfo("Asia/Seoul")).strftime('%Y-%m-%d')
            bid_count = len(results)
            subject = f"[NARA] {today} 나라장터 분석 보고서 ({bid_count}건)"

        # HTML 본문 렌더링
        html_body = self._render_html(results)

        # 이메일 메시지 구성
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = self.smtp_user
        msg['To'] = ', '.join(recipients)

        # 텍스트 버전 (HTML 미지원 클라이언트용)
        text_body = self._render_text(results)
        msg.attach(MIMEText(text_body, 'plain', 'utf-8'))

        # HTML 버전
        msg.attach(MIMEText(html_body, 'html', 'utf-8'))

        # SMTP 전송
        try:
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                server.starttls(context=ssl.create_default_context())
                server.login(self.smtp_user, self.smtp_password)
                server.send_message(msg)

            logger.info("이메일 전송 완료: %d명에게 발송 (%s)", len(recipients), subject)
            return True

        except smtplib.SMTPAuthenticationError:
            logger.error("SMTP 인증 실패. 사용자명/비밀번호를 확인하세요.", exc_info=True)
            return False
        except smtplib.SMTPException as e:
            logger.error("이메일 전송 실패 (SMTP): %s", e, exc_info=True)
            return False
        except Exception as e:
            logger.error("이메일 전송 실패: %s", e, exc_info=True)
            return False

    # ══════════════════════════════════════════════
    # 템플릿 렌더링
    # ══════════════════════════════════════════════

    def _render_html(self, results: list[dict]) -> str:
        """
        Jinja2 템플릿으로 HTML 이메일 본문을 생성합니다.

        Args:
            results: 분석 결과 리스트

        Returns:
            렌더링된 HTML 문자열
        """
        now = datetime.now(tz=ZoneInfo("Asia/Seoul"))
        report_date = now.strftime('%Y년 %m월 %d일')
        generated_at = now.strftime('%Y-%m-%d %H:%M:%S')

        # 결과 데이터를 템플릿 형식으로 변환
        template_results = []
        high_count = 0
        mid_count = 0
        low_count = 0

        for rank, result in enumerate(results, 1):
            bid = result.get('bid', result.get('bid_info', result))
            strategy = result.get('strategy', result)

            title = bid.get('title', bid.get('bidNtceNm', '제목 없음'))
            org = bid.get('organization', bid.get('ntceInsttNm', ''))
            budget = self._format_budget(bid.get('budget', bid.get('presmptPrce', '')))
            deadline = bid.get('deadline', bid.get('bidClseDt', ''))

            # 관련도 점수 처리
            relevance = result.get('relevance_score', 0)
            relevance_class = self._get_score_class(relevance)

            # 매칭 정보 처리
            best_match = result.get('best_match', {})
            match_business = ''
            match_score = 0
            match_class = ''
            match_recommendation = ''
            if best_match:
                match_business = best_match.get('business', {}).get('name', '')
                match_score = best_match.get('score', 0)
                match_class = self._get_score_class(match_score)
                match_recommendation = best_match.get('recommendation', '')

            # 통계 카운트
            total_score = match_score or relevance
            if total_score >= 70:
                high_count += 1
            elif total_score >= 45:
                mid_count += 1
            else:
                low_count += 1

            template_results.append({
                'rank': rank,
                'title': title,
                'organization': org,
                'budget': budget,
                'deadline': str(deadline)[:10] if deadline else '',
                'relevance_score': relevance,
                'relevance_class': relevance_class,
                'match_business': match_business,
                'match_score': match_score,
                'match_class': match_class,
                'match_recommendation': match_recommendation,
                'bid_summary': strategy.get('bid_summary', ''),
                'action_items': strategy.get('action_items', []),
                'overall_recommendation': strategy.get('overall_recommendation', ''),
            })

        # 템플릿 렌더링
        html = self._template.render(
            report_date=report_date,
            generated_at=generated_at,
            total_count=len(results),
            high_count=high_count,
            mid_count=mid_count,
            low_count=low_count,
            results=template_results,
        )

        return html

    def _render_text(self, results: list[dict]) -> str:
        """
        HTML 미지원 클라이언트용 텍스트 버전을 생성합니다.

        Args:
            results: 분석 결과 리스트

        Returns:
            텍스트 형식의 이메일 본문
        """
        now = datetime.now(tz=ZoneInfo("Asia/Seoul"))
        lines = [
            '═' * 50,
            '  🏛️ NARA Analyzer - 일일 분석 보고서',
            f'  📅 {now.strftime("%Y년 %m월 %d일")}',
            '═' * 50,
            '',
            f'총 {len(results)}건의 공고를 분석했습니다.',
            '',
        ]

        for rank, result in enumerate(results, 1):
            bid = result.get('bid', result.get('bid_info', result))
            strategy = result.get('strategy', result)

            title = bid.get('title', bid.get('bidNtceNm', ''))
            org = bid.get('organization', bid.get('ntceInsttNm', ''))
            budget = self._format_budget(bid.get('budget', ''))
            deadline = bid.get('deadline', bid.get('bidClseDt', ''))
            relevance = result.get('relevance_score', 0)

            lines.append(f'─── [{rank}] ───')
            lines.append(f'📄 {title}')
            lines.append(f'🏢 {org}')
            lines.append(f'💰 {budget}  📅 마감: {deadline}')

            if relevance:
                emoji = '🟢' if relevance >= 70 else ('🟡' if relevance >= 45 else '🔴')
                lines.append(f'{emoji} 관련도: {relevance:.0f}점')

            best_match = result.get('best_match', {})
            if best_match:
                match_biz = best_match.get('business', {}).get('name', '')
                match_score = best_match.get('score', 0)
                lines.append(f'🏢 매칭: {match_biz} ({match_score:.0f}점)')

            recommendation = strategy.get('overall_recommendation', '')
            if recommendation:
                lines.append(f'🎯 권고: {recommendation}')

            lines.append('')

        lines.extend([
            '─' * 50,
            '이 보고서는 NARA Analyzer에 의해 자동 생성되었습니다.',
            'AI 분석 결과는 참고용이며, 최종 판단은 공고 원문 기준입니다.',
        ])

        return '\n'.join(lines)

    # ══════════════════════════════════════════════
    # 유틸리티
    # ══════════════════════════════════════════════

    @staticmethod
    def _get_score_class(score: float) -> str:
        """점수에 따른 CSS 클래스를 반환합니다."""
        if score >= 70:
            return 'score-high'
        elif score >= 45:
            return 'score-mid'
        return 'score-low'

    @staticmethod
    def _format_budget(budget: Any) -> str:
        """예산을 가독성 좋은 형식으로 포맷합니다."""
        return format_budget(budget, unit="만원")
