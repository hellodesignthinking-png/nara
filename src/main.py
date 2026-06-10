"""
NARA Analyzer — 나라장터 용역 자동 분석 시스템
메인 실행 파이프라인

사용법:
    python -m src.main analyze              # 오늘의 공고 분석
    python -m src.main analyze --from YYYYMMDD --to YYYYMMDD  # 기간 지정
    python -m src.main register             # 사업자 등록
    python -m src.main businesses           # 사업자 목록 확인
    python -m src.main schedule --time HH:MM  # 매일 자동 실행
"""

import argparse
import json
import logging
import sys
from datetime import datetime, timedelta

from src.config import load_config
from src.models.database import DatabaseManager
from src.models.schemas import BusinessProfile, AnalysisResult
from src.collectors.bid_collector import BidCollector
from src.collectors.award_collector import AwardCollector
from src.collectors.news_collector import NewsCollector
from src.analyzers.keyword_filter import KeywordFilter
from src.analyzers.biz_matcher import BizMatcher
from src.analyzers.llm_analyzer import LLMAnalyzer
from src.analyzers.strategy_engine import StrategyEngine
from src.reporters.cli_reporter import CLIReporter
from src.utils.converters import biz_profile_to_matcher_dict as _biz_profile_to_matcher_dict
from src.utils.converters import bid_to_matcher_dict as _bid_to_matcher_dict

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
logger = logging.getLogger("nara")


def run_analysis(config, db, start_date=None, end_date=None):
    """
    전체 분석 파이프라인을 실행합니다.

    흐름:
    1. 나라장터 API로 용역 공고 수집
    2. 키워드 1차 필터링
    3. 등록된 사업자들과 매칭 점수 계산
    4. 과거 낙찰 데이터 수집
    5. 관련 뉴스 기사 수집
    6. LLM 심층 분석 + 전략 보고서 생성
    7. CLI 출력
    """
    try:
        reporter = CLIReporter()
        reporter.print_header()

        # ── 1단계: 공고 수집 ─────────────────────────────
        logger.info("📋 1단계: 나라장터 용역 공고 수집 중...")
        bid_collector = BidCollector(config)

        if start_date and end_date:
            bids = bid_collector.collect_bids_by_date(start_date, end_date)
        else:
            bids = bid_collector.collect_today_bids()

        if not bids:
            reporter.console.print("\n[yellow]⚠️ 수집된 공고가 없습니다.[/yellow]")
            return

        logger.info(f"  → 총 {len(bids)}건 공고 수집 완료")

        # DB에 저장
        db.save_bids(bids)

        # ── 2단계: 키워드 필터링 ──────────────────────────
        logger.info("🔍 2단계: 키워드 기반 1차 필터링 중...")
        keyword_filter = KeywordFilter(config.keywords)

        # BidAnnouncement 객체를 dict로 변환하여 필터링
        bid_dicts = [_bid_to_matcher_dict(b) for b in bids]
        filtered_bids = keyword_filter.filter_bids(bid_dicts, min_score=config.min_relevance_score)
        logger.info(f"  → {len(filtered_bids)}건 관심 공고 필터링됨")

        if not filtered_bids:
            reporter.console.print("\n[yellow]⚠️ 키워드에 매칭되는 공고가 없습니다.[/yellow]")
            reporter.console.print(f"[dim]현재 키워드: {', '.join(config.keywords)}[/dim]")
            return

        # ── 3단계: 사업자 매칭 ────────────────────────────
        logger.info("🏢 3단계: 사업자-공고 매칭 분석 중...")
        biz_profiles = db.get_businesses()

        if not biz_profiles:
            reporter.console.print("\n[yellow]⚠️ 등록된 사업자가 없습니다. 먼저 사업자를 등록해주세요.[/yellow]")
            reporter.console.print("[dim]실행: python -m src.main register[/dim]")
            return

        # BusinessProfile → matcher dict 변환
        biz_dicts = [_biz_profile_to_matcher_dict(bp) for bp in biz_profiles]

        biz_matcher = BizMatcher()
        match_results = biz_matcher.match_all_bids(biz_dicts, filtered_bids)
        logger.info(f"  → {len(biz_profiles)}개 사업자와 매칭 완료")

        # ── 4단계: 과거 데이터 + 뉴스 수집 ───────────────
        logger.info("📰 4단계: 과거 낙찰 데이터 및 뉴스 수집 중...")
        award_collector = AwardCollector(config)
        news_collector = NewsCollector(config)

        for result in match_results:
            bid = result["bid"]
            bid_title = bid.get("title", bid.get("bidNtceNm", ""))

            # 과거 낙찰 정보 수집
            try:
                past_awards = award_collector.collect_awards_by_keyword(
                    bid_title, years_back=config.past_years
                )
                result["past_awards"] = past_awards
                if past_awards:
                    db.save_awards(past_awards)
            except Exception as e:
                logger.warning(f"  ⚠️ 낙찰 정보 수집 실패: {e}")
                result["past_awards"] = []

            # 관련 뉴스 수집
            try:
                org_name = bid.get("org_name", bid.get("ntceInsttNm", ""))
                if org_name:
                    news = news_collector.collect_org_news(
                        org_name, config.keywords, years_back=config.past_years
                    )
                    result["news_articles"] = news
                    if news:
                        db.save_news(news)
                else:
                    result["news_articles"] = []
            except Exception as e:
                logger.warning(f"  ⚠️ 뉴스 수집 실패: {e}")
                result["news_articles"] = []

        # ── 5단계: AI 전략 보고서 생성 ────────────────────
        logger.info("🤖 5단계: AI 전략 보고서 생성 중...")
        if config.llm_engine == "gemini":
            llm_analyzer = LLMAnalyzer(
                api_key=config.gemini_api_key,
                model=config.gemini_model,
                engine="gemini",
            )
        else:
            llm_analyzer = LLMAnalyzer(
                api_key=config.openai_api_key,
                model=config.openai_model,
                engine="openai",
            )
        strategy_engine = StrategyEngine(llm_analyzer)

        final_results = []
        for result in match_results:
            bid = result["bid"]
            best_match = result.get("best_match") or {}
            business = best_match.get("business", {})

            # 과거 낙찰 정보를 dict 리스트로 변환
            past_award_dicts = []
            for aw in result.get("past_awards", []):
                if hasattr(aw, "to_dict"):
                    past_award_dicts.append(aw.to_dict())
                elif isinstance(aw, dict):
                    past_award_dicts.append(aw)

            # 뉴스를 dict 리스트로 변환
            news_dicts = []
            for ns in result.get("news_articles", []):
                if hasattr(ns, "to_dict"):
                    news_dicts.append(ns.to_dict())
                elif isinstance(ns, dict):
                    news_dicts.append(ns)

            try:
                strategy = strategy_engine.generate_strategy(
                    bid=bid,
                    business_profile=business,
                    rfp_text=bid.get("rfp_text", ""),
                    past_awards=past_award_dicts,
                    news_articles=news_dicts,
                )
                result["strategy"] = strategy

                # DB에 분석 결과 저장
                analysis = AnalysisResult(
                    bid_ntce_no=bid.get("bid_ntce_no", ""),
                    biz_id=business.get("biz_id", ""),
                    relevance_score=result.get("relevance_score", 0),
                    match_score=best_match.get("score", 0),
                    summary=strategy.get("bid_summary", ""),
                    strategy_report=json.dumps(strategy, ensure_ascii=False),
                    competitors=strategy.get("competitor_analysis", ""),
                )
                db.save_analysis(analysis)

            except Exception as e:
                logger.warning(f"  ⚠️ 전략 보고서 생성 실패 ({bid.get('title', '')}): {e}")
                result["strategy"] = {"error": str(e)}

            final_results.append(result)

        # ── 6단계: 보고서 출력 ────────────────────────────
        logger.info("📊 6단계: 보고서 출력 중...")
        reporter.print_daily_report(final_results)

        # 이메일 전송 (설정된 경우)
        if config.smtp_user and config.email_recipients:
            try:
                from src.reporters.email_reporter import EmailReporter

                email_reporter = EmailReporter(
                    smtp_host=config.smtp_host,
                    smtp_port=config.smtp_port,
                    smtp_user=config.smtp_user,
                    smtp_password=config.smtp_password,
                )
                email_reporter.send_daily_report(final_results, config.email_recipients)
                logger.info("  ✅ 이메일 전송 완료")
            except Exception as e:
                logger.warning(f"  ⚠️ 이메일 전송 실패: {e}")

        logger.info("✅ 분석 완료!")
        return final_results

    except Exception as e:
        logger.error("분석 파이프라인 실행 중 예상치 못한 오류 발생: %s", e, exc_info=True)
        raise


def register_business(db):
    """대화형으로 사업자를 등록합니다."""
    from rich.console import Console
    from rich.panel import Panel

    console = Console()
    console.print(Panel("🏢 사업자 등록", style="bold cyan"))

    print()
    biz_id = input("사업자등록번호: ").strip()
    if not biz_id:
        print("❌ 사업자등록번호를 입력해주세요.")
        return

    company_name = input("회사명: ").strip()
    ceo_name = input("대표자명: ").strip()

    print("\n[업종 입력] 쉼표로 구분 (예: SW개발,AI,데이터분석)")
    business_types = [t.strip() for t in input("업종: ").split(",") if t.strip()]

    print("\n[면허/자격 입력] 쉼표로 구분 (예: 정보통신공사업,SW사업자)")
    licenses = [l.strip() for l in input("보유 면허: ").split(",") if l.strip()]

    print("\n[지역 입력] 쉼표로 구분 (예: 서울,경기)")
    regions = [r.strip() for r in input("활동 가능 지역: ").split(",") if r.strip()]

    print("\n[관심 키워드 입력] 쉼표로 구분 (예: AI,빅데이터,클라우드)")
    keywords = [k.strip() for k in input("관심 키워드: ").split(",") if k.strip()]

    annual_revenue = input("\n연매출(원, 숫자만): ").strip()
    annual_revenue = int(annual_revenue) if annual_revenue.isdigit() else 0

    employee_count = input("직원 수: ").strip()
    employee_count = int(employee_count) if employee_count.isdigit() else 0

    min_budget = input("참여 관심 최소 예산(원): ").strip()
    min_budget = int(min_budget) if min_budget.isdigit() else 0

    max_budget = input("참여 가능 최대 예산(원): ").strip()
    max_budget = int(max_budget) if max_budget.isdigit() else 0

    print("\n[과거 수행실적 입력] 한 줄에 하나씩. 빈 줄 입력 시 종료.")
    past_projects = []
    while True:
        proj = input("실적: ").strip()
        if not proj:
            break
        past_projects.append(proj)

    # BusinessProfile dataclass 객체로 생성
    profile = BusinessProfile(
        biz_id=biz_id,
        company_name=company_name,
        ceo_name=ceo_name,
        business_types=business_types,
        licenses=licenses,
        regions=regions,
        past_projects=past_projects,
        annual_revenue=annual_revenue,
        employee_count=employee_count,
        keywords=keywords,
        min_budget=min_budget,
        max_budget=max_budget,
    )

    db.add_business(profile)
    console.print(f"\n[green]✅ '{company_name}' 사업자가 등록되었습니다![/green]")


def list_businesses(db):
    """등록된 사업자 목록을 출력합니다."""
    reporter = CLIReporter()
    businesses = db.get_businesses()

    if not businesses:
        reporter.console.print("\n[yellow]⚠️ 등록된 사업자가 없습니다.[/yellow]")
        reporter.console.print("[dim]실행: python -m src.main register[/dim]")
        return

    # BusinessProfile → dict 변환하여 reporter에 전달
    biz_dicts = []
    for bp in businesses:
        d = bp.to_dict()
        # 표시를 위해 JSON 필드를 파싱
        d["business_types"] = bp.business_types
        d["licenses"] = bp.licenses
        d["regions"] = bp.regions
        d["keywords"] = bp.keywords
        biz_dicts.append(d)

    reporter.print_business_profiles(biz_dicts)


def run_schedule(config, db, time_str):
    """매일 지정된 시간에 분석을 자동 실행합니다."""
    import schedule as sched
    import time

    from rich.console import Console

    console = Console()
    console.print(f"\n[bold green]⏰ 매일 {time_str}에 자동 분석이 실행됩니다.[/bold green]")
    console.print("[dim]종료하려면 Ctrl+C를 누르세요.[/dim]\n")

    sched.every().day.at(time_str).do(run_analysis, config=config, db=db)

    try:
        while True:
            sched.run_pending()
            time.sleep(60)
    except KeyboardInterrupt:
        console.print("\n[yellow]⏹ 스케줄링이 종료되었습니다.[/yellow]")


def main():
    """메인 엔트리포인트"""
    parser = argparse.ArgumentParser(
        description="🏛️ NARA Analyzer — 나라장터 용역 자동 분석 시스템",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", help="실행할 명령")

    # analyze 커맨드
    analyze_parser = subparsers.add_parser("analyze", help="공고 분석 실행")
    analyze_parser.add_argument("--from", dest="from_date", help="시작일 (YYYYMMDD)")
    analyze_parser.add_argument("--to", dest="to_date", help="종료일 (YYYYMMDD)")

    # register 커맨드
    subparsers.add_parser("register", help="사업자 등록")

    # businesses 커맨드
    subparsers.add_parser("businesses", help="등록된 사업자 목록")

    # schedule 커맨드
    schedule_parser = subparsers.add_parser("schedule", help="매일 자동 실행")
    schedule_parser.add_argument(
        "--time", default="08:00", help="실행 시간 (HH:MM, 기본 08:00)"
    )

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    # 설정 로드
    config = load_config()

    # 설정 검증
    warnings = config.validate()
    if warnings:
        from rich.console import Console

        console = Console()
        for w in warnings:
            console.print(f"[yellow]⚠️ {w}[/yellow]")
        print()

    # DB 초기화 (context manager 사용)
    with DatabaseManager(config.db_path) as db:
        db.init_db()

        # 커맨드 실행
        if args.command == "analyze":
            run_analysis(config, db, args.from_date, args.to_date)
        elif args.command == "register":
            register_business(db)
        elif args.command == "businesses":
            list_businesses(db)
        elif args.command == "schedule":
            run_schedule(config, db, args.time)


if __name__ == "__main__":
    main()
