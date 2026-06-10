"""
Rich 기반 CLI 보고서 출력 모듈

터미널에서 세련된 형태로 분석 결과를 출력합니다.
Panel, Table, Markdown, 이모지, 그래디언트 색상 등을 활용하여
가독성 높은 보고서를 제공합니다.
"""

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from src.utils.formatters import format_budget

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.markdown import Markdown
from rich.text import Text
from rich.columns import Columns
from rich.rule import Rule
from rich import box


class CLIReporter:
    """
    Rich 라이브러리 기반 터미널 보고서 출력기

    공고 분석 결과를 세련된 터미널 UI로 출력합니다.
    점수별 색상 분류, 이모지, 마크다운 렌더링 등을 지원합니다.
    """

    # 점수별 색상·이모지 매핑
    SCORE_THRESHOLDS = [
        (70, 'green', '🟢'),
        (45, 'yellow', '🟡'),
        (0, 'red', '🔴'),
    ]

    # 표시 상수
    TITLE_MAX_LEN = 38
    ORG_MAX_LEN = 35
    MAX_DISPLAY_COUNT = 10

    def __init__(self):
        """CLI 보고서 출력기를 초기화합니다."""
        self.console = Console()

    # ══════════════════════════════════════════════
    # 공개 API
    # ══════════════════════════════════════════════

    def print_header(self):
        """NARA Analyzer 메인 헤더를 출력합니다."""
        now = datetime.now(tz=ZoneInfo("Asia/Seoul"))
        date_str = now.strftime('%Y년 %m월 %d일 (%A)')
        time_str = now.strftime('%H:%M:%S')

        # 요일 한글화
        weekday_map = {
            'Monday': '월요일', 'Tuesday': '화요일', 'Wednesday': '수요일',
            'Thursday': '목요일', 'Friday': '금요일',
            'Saturday': '토요일', 'Sunday': '일요일',
        }
        for eng, kor in weekday_map.items():
            date_str = date_str.replace(eng, kor)

        header_text = Text()
        header_text.append("🏛️  NARA ", style="bold bright_cyan")
        header_text.append("Analyzer", style="bold bright_magenta")
        header_text.append("  🏛️", style="bold bright_cyan")

        subtitle = Text()
        subtitle.append("나라장터 용역 자동 분석 시스템", style="dim white")

        date_line = Text()
        date_line.append(f"📅 {date_str}  ", style="bright_white")
        date_line.append(f"⏰ {time_str}", style="bright_white")

        content = Text.assemble(
            header_text, "\n",
            subtitle, "\n",
            date_line,
        )

        panel = Panel(
            content,
            border_style="bright_cyan",
            box=box.DOUBLE_EDGE,
            padding=(1, 4),
        )
        self.console.print(panel)
        self.console.print()

    def print_bid_summary_table(self, results: list[dict]):
        """
        공고 요약 테이블을 출력합니다.

        컬럼: 순위, 공고명, 발주기관, 예산, 마감일, 관련도, 매칭 사업자, 매칭 점수
        관련도/매칭 점수에 따라 색상을 다르게 표시합니다.

        Args:
            results: 분석 결과 리스트
                각 항목은 아래 키를 포함할 수 있음:
                - bid / bid_info: 공고 정보
                - relevance_score: 관련도 점수
                - best_match: 최적 매칭 사업자 정보
                - strategy: 전략 보고서 정보
        """
        if not results:
            self.console.print("[dim]표시할 공고가 없습니다.[/dim]")
            return

        # 테이블 헤더 구성
        table = Table(
            title="📋 공고 분석 요약",
            title_style="bold bright_yellow",
            box=box.ROUNDED,
            border_style="bright_blue",
            header_style="bold bright_white on dark_blue",
            show_lines=True,
            padding=(0, 1),
        )

        table.add_column("순위", justify="center", style="bold", width=4)
        table.add_column("공고명", min_width=25, max_width=40, no_wrap=False)
        table.add_column("발주기관", min_width=10, max_width=18, no_wrap=False)
        table.add_column("예산", justify="right", min_width=10)
        table.add_column("마감일", justify="center", min_width=10)
        table.add_column("관련도", justify="center", width=8)
        table.add_column("매칭 사업자", min_width=10, max_width=15, no_wrap=False)
        table.add_column("매칭점수", justify="center", width=8)

        for rank, result in enumerate(results, 1):
            # 공고 정보 추출
            bid = result.get('bid', result.get('bid_info', result))
            title = bid.get('title', bid.get('bidNtceNm', ''))
            org = bid.get('organization', bid.get('ntceInsttNm', ''))
            budget = self._format_budget(bid.get('budget', bid.get('presmptPrce', '')))
            deadline = bid.get('deadline', bid.get('bidClseDt', ''))

            # 관련도 점수
            relevance = result.get('relevance_score', 0)
            rel_color, rel_emoji = self._get_score_style(relevance)
            relevance_text = f"{rel_emoji} {relevance:.0f}" if relevance is not None else "-"

            # 매칭 정보
            best_match = result.get('best_match', {})
            if best_match:
                match_biz = best_match.get('business', {}).get('name', '-')
                match_score = best_match.get('score', 0)
                ms_color, ms_emoji = self._get_score_style(match_score)
                match_score_text = f"{ms_emoji} {match_score:.0f}"
            else:
                match_biz = '-'
                match_score_text = '-'
                ms_color = 'dim'

            # 마감일이 너무 길면 날짜 부분만 추출
            if deadline and len(str(deadline)) > 10:
                deadline = str(deadline)[:10]

            # 제목이 너무 길면 줄임
            display_title = title
            if len(display_title) > self.TITLE_MAX_LEN:
                display_title = display_title[:self.ORG_MAX_LEN] + '...'

            table.add_row(
                str(rank),
                display_title,
                org,
                budget,
                str(deadline),
                f"[{rel_color}]{relevance_text}[/{rel_color}]",
                match_biz,
                f"[{ms_color}]{match_score_text}[/{ms_color}]",
            )

        self.console.print(table)
        self.console.print()

    def print_strategy_report(self, result: dict):
        """
        개별 공고의 상세 전략 보고서를 Panel로 출력합니다.

        마크다운 형태로 전략 보고서 내용을 렌더링합니다.

        Args:
            result: 전략 보고서 dict
                - bid_info: 공고 기본 정보
                - bid_summary / competitor_analysis / ... 전략 항목들
                - metadata: 분석 메타 정보
        """
        bid_info = result.get('bid_info', {})
        title = bid_info.get('title', result.get('bid', {}).get('title', '공고명 없음'))

        self.console.print(Rule(style="bright_cyan"))
        self.console.print()

        # ─── 공고 기본 정보 Panel ───
        info_lines = []
        if bid_info.get('organization'):
            info_lines.append(f"🏢 **발주기관**: {bid_info['organization']}")
        if bid_info.get('budget'):
            info_lines.append(f"💰 **추정가격**: {self._format_budget(bid_info['budget'])}")
        if bid_info.get('deadline'):
            info_lines.append(f"📅 **입찰마감**: {bid_info['deadline']}")
        if bid_info.get('bid_number'):
            info_lines.append(f"📌 **공고번호**: {bid_info['bid_number']}")

        if info_lines:
            info_md = Markdown('\n\n'.join(info_lines))
            info_panel = Panel(
                info_md,
                title=f"📄 {title}",
                title_align="left",
                border_style="bright_yellow",
                box=box.HEAVY,
                padding=(1, 2),
            )
            self.console.print(info_panel)
            self.console.print()

        # ─── 각 전략 섹션 출력 ───
        sections = [
            ('📊 사업 핵심 분석', 'bid_summary', 'bright_green'),
            ('🔍 경쟁사 분석', 'competitor_analysis', 'bright_cyan'),
            ('💡 차별화 전략', 'differentiation_strategy', 'bright_magenta'),
            ('⚠️ 위험 요소·주의사항', 'risk_factors', 'bright_red'),
            ('💰 예산 분석', 'budget_analysis', 'bright_yellow'),
        ]

        for section_title, key, color in sections:
            content = result.get(key, '')
            if content:
                md_content = Markdown(str(content))
                section_panel = Panel(
                    md_content,
                    title=section_title,
                    title_align="left",
                    border_style=color,
                    box=box.ROUNDED,
                    padding=(1, 2),
                )
                self.console.print(section_panel)
                self.console.print()

        # ─── 행동 체크리스트 ───
        action_items = result.get('action_items', [])
        if action_items:
            checklist_lines = []
            for i, item in enumerate(action_items, 1):
                checklist_lines.append(f"  {i}. {item}")

            checklist_text = '\n'.join(checklist_lines)
            checklist_panel = Panel(
                checklist_text,
                title="✅ 입찰 준비 체크리스트",
                title_align="left",
                border_style="bright_green",
                box=box.ROUNDED,
                padding=(1, 2),
            )
            self.console.print(checklist_panel)
            self.console.print()

        # ─── 종합 권고 ───
        recommendation = result.get('overall_recommendation', '')
        if recommendation:
            rec_panel = Panel(
                Markdown(f"**{recommendation}**"),
                title="🎯 종합 권고",
                title_align="left",
                border_style="bold bright_white",
                box=box.DOUBLE_EDGE,
                padding=(1, 2),
            )
            self.console.print(rec_panel)
            self.console.print()

        # ─── 메타 정보 ───
        metadata = result.get('metadata', {})
        if metadata:
            engine = metadata.get('analysis_engine', 'unknown')
            analyzed_at = metadata.get('analyzed_at', '')
            sources = metadata.get('data_sources', {})

            meta_parts = [f"분석 엔진: {engine}"]
            if analyzed_at:
                meta_parts.append(f"분석 시각: {analyzed_at}")
            if sources:
                rfp_status = '✔' if sources.get('rfp_available') else '✘'
                meta_parts.append(
                    f"데이터: RFP {rfp_status} | "
                    f"과거이력 {sources.get('past_awards_count', 0)}건 | "
                    f"뉴스 {sources.get('news_articles_count', 0)}건"
                )

            meta_text = ' │ '.join(meta_parts)
            self.console.print(f"  [dim]{meta_text}[/dim]")
            self.console.print()

    def print_business_profiles(self, businesses: list[dict]):
        """
        등록된 사업자 목록을 테이블로 출력합니다.

        Args:
            businesses: 사업자 프로필 리스트
        """
        if not businesses:
            self.console.print("[dim]등록된 사업자가 없습니다.[/dim]")
            return

        table = Table(
            title="🏢 등록 사업자 목록",
            title_style="bold bright_cyan",
            box=box.ROUNDED,
            border_style="bright_blue",
            header_style="bold bright_white on dark_blue",
            show_lines=True,
            padding=(0, 1),
        )

        table.add_column("No.", justify="center", width=4, style="bold")
        table.add_column("업체명", min_width=15, max_width=25)
        table.add_column("업종", min_width=15, max_width=25, no_wrap=False)
        table.add_column("보유 면허", min_width=15, max_width=30, no_wrap=False)
        table.add_column("소재지", justify="center", min_width=8)
        table.add_column("참여 예산범위", justify="center", min_width=12)
        table.add_column("실적 수", justify="center", width=6)

        for i, biz in enumerate(businesses, 1):
            name = biz.get('name', '-')
            types = ', '.join(biz.get('business_types', ['-']))
            licenses = ', '.join(biz.get('licenses', ['-']))
            region = biz.get('region', '-')

            budget_range = biz.get('budget_range', {})
            if budget_range:
                bmin = budget_range.get('min', 0)
                bmax = budget_range.get('max', 0)
                budget_str = f"{bmin:,.0f}~{bmax:,.0f}만원"
            else:
                budget_str = '-'

            past_count = len(biz.get('past_projects', []))

            table.add_row(
                str(i), name, types, licenses, region, budget_str, str(past_count)
            )

        self.console.print(table)
        self.console.print()

    def print_daily_report(self, results: list[dict]):
        """
        전체 일일 보고서를 출력합니다.

        헤더 → 사업자 정보 → 요약 테이블 → 각 공고 상세 보고서 순으로 출력합니다.

        Args:
            results: 분석 결과 리스트
                각 항목에 아래 키 포함:
                - bid / bid_info: 공고 정보
                - relevance_score: 관련도
                - best_match: 사업자 매칭 결과
                - strategy: 전략 보고서 (선택)
        """
        # ─── 1. 헤더 ───
        self.print_header()

        # ─── 2. 요약 통계 ───
        self._print_summary_stats(results)

        # ─── 3. 요약 테이블 ───
        self.print_bid_summary_table(results)

        # ─── 4. 각 공고별 상세 보고서 ───
        for i, result in enumerate(results, 1):
            strategy = result.get('strategy', result)
            if strategy and strategy.get('bid_summary'):
                self.console.print(
                    Rule(f"[bold bright_cyan]  상세 보고서 {i}/{len(results)}  [/bold bright_cyan]",
                         style="bright_cyan")
                )
                self.console.print()
                self.print_strategy_report(strategy)

        # ─── 5. 종료 구분선 ───
        self.console.print(Rule(style="bright_cyan"))
        end_text = Text()
        end_text.append("🏁 일일 분석 보고서 종료", style="bold bright_cyan")
        end_text.append(f"  ({datetime.now(tz=ZoneInfo('Asia/Seoul')).strftime('%H:%M:%S')})", style="dim")
        self.console.print(end_text, justify="center")
        self.console.print()

    # ══════════════════════════════════════════════
    # 내부 유틸리티
    # ══════════════════════════════════════════════

    def _print_summary_stats(self, results: list[dict]):
        """요약 통계를 출력합니다."""
        total = len(results)
        high_rel = sum(1 for r in results if r.get('relevance_score', 0) >= 70)
        med_rel = sum(1 for r in results if 45 <= r.get('relevance_score', 0) < 70)
        low_rel = total - high_rel - med_rel

        high_match = sum(
            1 for r in results
            if r.get('best_match', {}).get('score', 0) >= 70
        )

        stats_text = (
            f"📊 분석 대상: [bold]{total}[/bold]건  │  "
            f"관련도 🟢 [green]{high_rel}[/green] "
            f"🟡 [yellow]{med_rel}[/yellow] "
            f"🔴 [red]{low_rel}[/red]  │  "
            f"매칭 적합: [bold green]{high_match}[/bold green]건"
        )

        stats_panel = Panel(
            stats_text,
            border_style="bright_blue",
            box=box.ROUNDED,
            padding=(0, 2),
        )
        self.console.print(stats_panel)
        self.console.print()

    def _get_score_style(self, score: float) -> tuple[str, str]:
        """점수에 따른 (색상, 이모지)를 반환합니다."""
        for threshold, color, emoji in self.SCORE_THRESHOLDS:
            if score >= threshold:
                return color, emoji
        return 'red', '🔴'

    @staticmethod
    def _format_budget(budget: Any) -> str:
        """예산을 가독성 좋은 형식으로 포맷합니다."""
        return format_budget(budget, unit="만원")
