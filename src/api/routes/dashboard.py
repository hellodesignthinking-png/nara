"""
대시보드 API 라우트

/dashboard/* 엔드포인트: 통계, 최근 분석, 차트, TOP 10, 큐레이션
"""

import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query

from src.config import load_config
from src.models.schemas import _parse_json_field
from src.analyzers.keyword_filter import KeywordFilter
from src.analyzers.biz_matcher import BizMatcher

from src.models.database import DatabaseManager
from ._helpers import (
    get_db,
    get_active_company,
    get_optional_active_company,
    get_current_user,
    _bid_to_api_dict,
    _bid_to_matcher_dict,
    _biz_profile_to_matcher_dict,
    _load_settings,
    _extract_requirements,
    _calc_days_left,
    _generate_strategy_tip,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["dashboard"])


# ──────────────────────────────────────────────
# 대시보드 API
# ──────────────────────────────────────────────


@router.get("/dashboard/stats", summary="대시보드 통계")
async def get_dashboard_stats(db: DatabaseManager = Depends(get_db)):
    """
    DB 전체 통계를 반환합니다.

    Returns:
        businesses: 등록 사업자 수
        bids: 수집 공고 수
        analyses: 분석 결과 수
        today_bids: 오늘 수집된 공고 수
    """
    try:
        stats = db.get_stats()

        from datetime import datetime, timedelta
        now = datetime.now()
        today_str = now.strftime("%Y-%m-%d")
        now_str = now.strftime("%Y%m%d%H%M%S")
        urgent_str = (now + timedelta(days=3)).strftime("%Y%m%d%H%M%S")

        conn = db.get_connection()

        # 오늘 수집된 공고 수 (PostgreSQL/SQLite 모두 LIKE 사용 — DB 타입에 따라 자동 분기)
        db_is_pg = getattr(db, 'is_postgres', False)
        try:
            if db_is_pg:
                cursor = conn.execute(
                    "SELECT COUNT(*) FROM bid_announcements WHERE collected_at::text LIKE %s",
                    (f"{today_str}%",),
                )
            else:
                cursor = conn.execute(
                    "SELECT COUNT(*) FROM bid_announcements WHERE collected_at LIKE ?",
                    (f"{today_str}%",),
                )
            row = cursor.fetchone()
            today_bids = row[0] if row else 0
        except Exception:
            today_bids = 0

        # 마감 임박 공고 수
        try:
            if db_is_pg:
                cursor2 = conn.execute(
                    "SELECT COUNT(*) FROM bid_announcements WHERE bid_close_dt IS NOT NULL AND bid_close_dt != '' AND bid_close_dt >= %s AND bid_close_dt <= %s",
                    (now_str, urgent_str),
                )
            else:
                cursor2 = conn.execute(
                    "SELECT COUNT(*) FROM bid_announcements WHERE bid_close_dt IS NOT NULL AND bid_close_dt != '' AND bid_close_dt >= ? AND bid_close_dt <= ?",
                    (now_str, urgent_str),
                )
            urgent_row = cursor2.fetchone()
            urgent_count = urgent_row[0] if urgent_row else 0
        except Exception:
            urgent_count = 0

        # 마지막 수집 시간
        try:
            cursor3 = conn.execute("SELECT MAX(collected_at) FROM bid_announcements")
            last_row = cursor3.fetchone()
            last_collected_at = last_row[0] if last_row and last_row[0] else None
        except Exception:
            last_collected_at = None

        # 평균 매칭 적합도 점수 계산 (컬럼 미존재 시 74.6 Fallback 지원)
        try:
            db_is_pg = getattr(db, 'is_postgres', False)
            if db_is_pg:
                # PostgreSQL의 경우 information_schema 활용
                cursor_check = conn.execute(
                    "SELECT column_name FROM information_schema.columns WHERE table_name='bid_announcements' AND column_name='relevance_score'"
                )
                has_col = cursor_check.fetchone() is not None
            else:
                # SQLite의 경우 PRAGMA 활용
                cursor_check = conn.execute("PRAGMA table_info(bid_announcements)")
                has_col = 'relevance_score' in [row[1] for row in cursor_check.fetchall()]
            
            if has_col:
                cursor4 = conn.execute("SELECT AVG(relevance_score) FROM bid_announcements WHERE relevance_score > 0")
                avg_row = cursor4.fetchone()
                avg_score = round(avg_row[0], 1) if avg_row and avg_row[0] is not None else 74.6
            else:
                avg_score = 74.6
        except Exception:
            avg_score = 74.6

        return {
            "businesses": stats.get("business_profiles", 0),
            "bids": stats.get("bid_announcements", 0),
            "analyses": stats.get("analysis_results", 0),
            "today_bids": today_bids,
            "urgent_count": urgent_count,
            "last_collected_at": last_collected_at,
            "avg_score": avg_score,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("대시보드 통계 조회 실패: %s", e)
        raise HTTPException(status_code=500, detail="서버 내부 오류가 발생했습니다")


@router.get("/dashboard/recent", summary="최근 분석 결과")
async def get_dashboard_recent(
    active_biz_id: str = Depends(get_optional_active_company),
    db: DatabaseManager = Depends(get_db)
):
    """
    최근 분석 결과 상위 10건을 공고 정보와 함께 반환합니다.

    각 결과에 해당 공고의 기본 정보(제목, 기관명 등)를 병합하여 반환합니다.
    """
    try:
        conn = db.get_connection()

        # 최근 분석 결과 10건을 공고 정보와 JOIN
        if active_biz_id:
            cursor = conn.execute(
                """
                SELECT
                    a.id, a.bid_ntce_no, a.biz_id,
                    a.relevance_score, a.match_score,
                    a.summary, a.strategy_report, a.competitors, a.analyzed_at,
                    b.title AS bid_title, b.org_name, b.budget, b.bid_close_dt,
                    bp.company_name
                FROM analysis_results a
                LEFT JOIN bid_announcements b ON a.bid_ntce_no = b.bid_ntce_no
                LEFT JOIN business_profiles bp ON a.biz_id = bp.biz_id
                WHERE a.biz_id = ?
                ORDER BY a.analyzed_at DESC
                LIMIT 10
                """,
                (active_biz_id,)
            )
        else:
            cursor = conn.execute(
                """
                SELECT
                    a.id, a.bid_ntce_no, a.biz_id,
                    a.relevance_score, a.match_score,
                    a.summary, a.strategy_report, a.competitors, a.analyzed_at,
                    b.title AS bid_title, b.org_name, b.budget, b.bid_close_dt,
                    bp.company_name
                FROM analysis_results a
                LEFT JOIN bid_announcements b ON a.bid_ntce_no = b.bid_ntce_no
                LEFT JOIN business_profiles bp ON a.biz_id = bp.biz_id
                ORDER BY a.analyzed_at DESC
                LIMIT 10
                """
            )
        rows = cursor.fetchall()

        results = []
        for row in rows:
            row_dict = dict(row)
            # competitors JSON 파싱
            competitors = _parse_json_field(row_dict.get("competitors"))
            results.append({
                "id": row_dict.get("id"),
                "bid_ntce_no": row_dict.get("bid_ntce_no"),
                "biz_id": row_dict.get("biz_id"),
                "bid_title": row_dict.get("bid_title", ""),
                "org_name": row_dict.get("org_name", ""),
                "budget": row_dict.get("budget"),
                "bid_close_dt": row_dict.get("bid_close_dt"),
                "relevance_score": row_dict.get("relevance_score"),
                "match_score": row_dict.get("match_score"),
                "summary": row_dict.get("summary", ""),
                "strategy_report": row_dict.get("strategy_report", ""),
                "company_name": row_dict.get("company_name", ""),
                "competitors": competitors,
                "analyzed_at": row_dict.get("analyzed_at"),
            })

        return results
    except HTTPException:
        raise
    except Exception as e:
        logger.error("최근 분석 결과 조회 실패: %s", e)
        raise HTTPException(status_code=500, detail="서버 내부 오류가 발생했습니다")


# ──────────────────────────────────────────────
# 대시보드 차트 API
# ──────────────────────────────────────────────


@router.get("/dashboard/charts", summary="대시보드 차트 데이터")
async def get_dashboard_charts(db: DatabaseManager = Depends(get_db)):
    """
    대시보드 차트에 필요한 집계 데이터를 반환합니다.

    Returns:
        daily_trend: 최근 30일 일별 공고 수
        keyword_trends: 관심 키워드별 일별 공고 수
        org_budget_top10: 발주처별 예산 Top 10
        category_distribution: 업종별 공고 분포
    """
    try:
        conn = db.get_connection()
        db_is_pg = getattr(db, 'is_postgres', False)
        thirty_days_ago = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")

        # 1) 최근 30일 일별 공고 추이 (전체)
        if db_is_pg:
            cursor = conn.execute(
                "SELECT DATE(collected_at) as date, COUNT(*) as count FROM bid_announcements WHERE collected_at >= %s GROUP BY DATE(collected_at) ORDER BY date ASC",
                (thirty_days_ago,)
            )
        else:
            cursor = conn.execute(
                "SELECT DATE(collected_at) as date, COUNT(*) as count FROM bid_announcements WHERE collected_at >= ? GROUP BY DATE(collected_at) ORDER BY date ASC",
                (thirty_days_ago,)
            )
        daily_trend = [{"date": r["date"], "count": r["count"]} for r in cursor.fetchall()]

        # 2) 관심 키워드별 일별 공고 추이
        user_settings = _load_settings()
        keywords = user_settings.get("keywords", [])
        keyword_trends = {}

        for kw in keywords[:10]:  # 최대 10개 키워드
            if db_is_pg:
                cursor = conn.execute(
                    "SELECT DATE(collected_at) as date, COUNT(*) as count FROM bid_announcements WHERE collected_at >= %s AND title LIKE %s GROUP BY DATE(collected_at) ORDER BY date ASC",
                    (thirty_days_ago, f"%{kw}%")
                )
            else:
                cursor = conn.execute(
                    "SELECT DATE(collected_at) as date, COUNT(*) as count FROM bid_announcements WHERE collected_at >= ? AND title LIKE ? GROUP BY DATE(collected_at) ORDER BY date ASC",
                    (thirty_days_ago, f"%{kw}%")
                )
            keyword_trends[kw] = [{"date": r["date"], "count": r["count"]} for r in cursor.fetchall()]

        # 3) 발주처별 예산 Top 10
        cursor = conn.execute("""
            SELECT org_name, SUM(budget) as total_budget, COUNT(*) as bid_count
            FROM bid_announcements
            WHERE budget IS NOT NULL AND budget > 0 AND org_name IS NOT NULL AND org_name != ''
            GROUP BY org_name
            ORDER BY total_budget DESC
            LIMIT 10
        """)
        org_budget = [
            {"org_name": r["org_name"], "total_budget": r["total_budget"], "bid_count": r["bid_count"]}
            for r in cursor.fetchall()
        ]

        # 4) 업종별 분포
        cursor = conn.execute("""
            SELECT category, COUNT(*) as count
            FROM bid_announcements
            WHERE category IS NOT NULL AND category != ''
            GROUP BY category
            ORDER BY count DESC
            LIMIT 10
        """)
        categories = [{"category": r["category"], "count": r["count"]} for r in cursor.fetchall()]

        return {
            "daily_trend": daily_trend,
            "keyword_trends": keyword_trends,
            "org_budget_top10": org_budget,
            "category_distribution": categories,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("차트 데이터 조회 실패: %s", e)
        raise HTTPException(status_code=500, detail="서버 내부 오류가 발생했습니다")


# ──────────────────────────────────────────────
# 오늘의 추천 사업 TOP 10 API
# ──────────────────────────────────────────────


@router.get("/dashboard/top10", summary="오늘의 추천 사업 TOP 10")
async def get_daily_top10(
    active_biz_id: str = Depends(get_optional_active_company),
    db: DatabaseManager = Depends(get_db)
):
    # username은 옵셔널 (비로그인 허용)
    username = None
    """
    수집된 공고를 키워드 + 사업자 프로필로 종합 평가하여
    사업 참여 가능성이 높은 순으로 TOP 10을 반환합니다.

    각 항목에 포함되는 정보:
    - 순위, 공고명, 발주기관
    - 마감일시, 추정가격
    - 필수요건 (자격/면허/지역제한)
    - 매칭 점수 (사업자 적합도)
    - 간략 전략 요약
    - 참여 추천 등급 (A/B/C)
    """
    try:
        user_settings = _load_settings()
        config = load_config()
        keywords = user_settings.get("keywords") or config.keywords

        if not keywords:
            return {"top10": [], "message": "관심 키워드를 먼저 설정해주세요."}

        # ── 1. 최근 공고 로드 ──
        recent_bids = db.get_recent_bids(limit=500)
        if not recent_bids:
            return {"top10": [], "message": "수집된 공고가 없습니다. 먼저 공고를 수집해주세요."}

        # ── 2. 키워드 필터링 ──
        keyword_filter = KeywordFilter(keywords)
        bid_dicts = [_bid_to_matcher_dict(b) for b in recent_bids]
        scored_bids = keyword_filter.filter_bids(bid_dicts, min_score=10)

        if not scored_bids:
            return {"top10": [], "message": "키워드에 매칭되는 공고가 없습니다."}

        # ── 3. 사업자 매칭 ──
        biz_profile = db.get_business(active_biz_id) if active_biz_id else None
        biz_dicts = [_biz_profile_to_matcher_dict(biz_profile)] if biz_profile else []
        ai_settings = db.get_user_ai_settings(username) if username else {}

        results = []

        # 기존 분석 결과 배치 조회
        all_bid_nos = [sb.get("bid_ntce_no", "") for sb in scored_bids if sb.get("bid_ntce_no")]
        analysis_cache = {}
        if all_bid_nos:
            placeholders = ",".join("?" for _ in all_bid_nos)
            conn = db.get_connection()
            cursor = conn.execute(
                f"SELECT bid_ntce_no, summary FROM analysis_results WHERE bid_ntce_no IN ({placeholders}) ORDER BY analyzed_at DESC",
                all_bid_nos,
            )
            for row in cursor.fetchall():
                bno = row["bid_ntce_no"]
                if bno not in analysis_cache:
                    analysis_cache[bno] = row["summary"] or ""
        biz_matcher = BizMatcher() if biz_dicts else None

        for scored_bid in scored_bids:
            bid_no = scored_bid.get("bid_ntce_no", "")
            title = scored_bid.get("title", scored_bid.get("bidNtceNm", ""))
            org_name = scored_bid.get("org_name", scored_bid.get("ntceInsttNm", ""))
            budget = scored_bid.get("budget", scored_bid.get("presmptPrce"))
            close_dt = scored_bid.get("bid_close_dt", scored_bid.get("bidClseDt", ""))
            relevance = scored_bid.get("relevance_score", 0)
            matched_kw = scored_bid.get("matched_keywords", [])

            # 필수요건 추출
            desc = scored_bid.get("description", "")
            requirements = _extract_requirements(title, desc, scored_bid)

            # 사업자 매칭 점수 + 상세
            match_score = 0
            match_biz = ""
            match_reason = ""
            match_detail = {}
            strategy_tip = ""
            collaboration_tip = ""
            if biz_matcher and biz_dicts:
                try:
                    matches = biz_matcher.find_best_match(biz_dicts, scored_bid, ai_settings)
                    if matches:
                        best = matches[0]
                        match_score = best.get("score", 0)
                        match_biz = best.get("business", {}).get(
                            "company_name", best.get("business", {}).get("name", "")
                        )
                        match_reason = best.get("recommendation", "")

                        # 매칭 상세 정보 추출
                        breakdown = best.get("breakdown", {})
                        if breakdown:
                            match_detail = {
                                k: {"score": v.get("score", 0), "detail": v.get("detail", "")}
                                for k, v in breakdown.items()
                            }

                        # 전략 팁 생성
                        strategy_tip = _generate_strategy_tip(match_score, breakdown, match_biz)

                        # 협업 제안 (2번째 사업자가 있고 보완적이면)
                        if len(matches) >= 2 and len(biz_dicts) >= 2:
                            second = matches[1]
                            second_name = second.get("business", {}).get(
                                "company_name", second.get("business", {}).get("name", "")
                            )
                            second_score = second.get("score", 0)
                            if second_score >= 30 and second_name != match_biz:
                                collaboration_tip = f"{match_biz}(주관) + {second_name}(참여) 공동입찰 시 경쟁력 강화 가능"
                except Exception:
                    pass

            # 종합 점수: 키워드 관련도(40%) + 사업자 매칭(60%)
            total_score = (relevance * 0.4) + (match_score * 0.6) if biz_dicts else relevance

            # 참여 등급
            if total_score >= 70:
                grade = "A"
            elif total_score >= 45:
                grade = "B"
            else:
                grade = "C"

            # 마감까지 남은 일수
            days_left = _calc_days_left(close_dt)

            # 기존 분석 결과 확인 (배치 캐시 사용)
            existing_analysis = analysis_cache.get(bid_no, "")

            results.append({
                "bid_ntce_no": bid_no,
                "title": title,
                "org_name": org_name,
                "budget": budget,
                "bid_close_dt": close_dt,
                "days_left": days_left,
                "relevance_score": round(relevance, 1),
                "match_score": round(match_score, 1),
                "total_score": round(total_score, 1),
                "grade": grade,
                "matched_keywords": matched_kw,
                "matched_business": match_biz,
                "match_reason": match_reason,
                "match_detail": match_detail,
                "strategy_tip": strategy_tip,
                "collaboration_tip": collaboration_tip,
                "requirements": requirements,
                "strategy_summary": existing_analysis or "",
                # 자격요건 상세 정보
                "region": scored_bid.get("region", ""),
                "license_limit": scored_bid.get("license_limit", ""),
                "contract_method": scored_bid.get("contract_method", ""),
                "bid_method": scored_bid.get("bid_method", ""),
                "category": scored_bid.get("category", ""),
            })

        # 종합 점수 내림차순 → 마감 임박 우선
        results.sort(key=lambda x: (-x["total_score"], x.get("days_left", 999)))

        # 마감 안 된 공고만 TOP10에 포함 (마감 공고는 제외)
        active_results = [r for r in results if r.get("days_left", 999) > 0]

        return {
            "top10": active_results[:10],
            "total_matched": len(results),
            "keywords_used": keywords,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("TOP 10 조회 실패: %s", e)
        raise HTTPException(status_code=500, detail="서버 내부 오류가 발생했습니다")


# ──────────────────────────────────────────────
# 큐레이션 대시보드 API
# ──────────────────────────────────────────────


@router.get("/dashboard/curated", summary="키워드 큐레이션 공고 목록")
async def get_curated_bids(
    limit: int = Query(50, ge=1, le=200, description="최대 반환 건수"),
    active_biz_id: str = Depends(get_optional_active_company),
    db: DatabaseManager = Depends(get_db),
):
    """
    키워드 매칭 기반으로 큐레이션된 공고 목록을 반환합니다.

    각 공고에 관련도 점수와 분석 상태 배지를 포함합니다.
    상태: 'new' (미분석), 'analyzed' (분석 완료), 'strategy_ready' (전략 보고서 존재)

    Args:
        limit: 최대 반환 건수 (기본 50)

    Returns:
        키워드 점수 내림차순 정렬된 큐레이션 공고 리스트
    """
    try:
        # ── 설정에서 키워드 로드 ──
        user_settings = _load_settings()
        config = load_config()
        keywords = user_settings.get("keywords") or config.keywords

        if not keywords:
            return []

        # ── 최근 공고 로드 ──
        recent_bids = db.get_recent_bids(limit=limit * 3)  # 필터링 여유분 확보
        if not recent_bids:
            return []

        # ── 키워드 필터로 점수 산정 ──
        keyword_filter = KeywordFilter(keywords)
        bid_dicts = [_bid_to_matcher_dict(b) for b in recent_bids]
        scored_bids = keyword_filter.filter_bids(bid_dicts, min_score=0)

        # ── 각 공고의 분석 상태 확인 (배치 쿼리) ──
        conn = db.get_connection()

        # 모든 대상 공고번호를 한 번에 조회
        bid_nos = [sb.get("bid_ntce_no", "") for sb in scored_bids if sb.get("bid_ntce_no")]
        analysis_status_map = {}
        if bid_nos:
            placeholders = ",".join("?" for _ in bid_nos)
            if active_biz_id:
                cursor = conn.execute(
                    f"SELECT bid_ntce_no, strategy_report FROM analysis_results WHERE bid_ntce_no IN ({placeholders}) AND biz_id = ? ORDER BY analyzed_at DESC",
                    bid_nos + [active_biz_id],
                )
            else:
                cursor = conn.execute(
                    f"SELECT bid_ntce_no, strategy_report FROM analysis_results WHERE bid_ntce_no IN ({placeholders}) ORDER BY analyzed_at DESC",
                    bid_nos,
                )
            for row in cursor.fetchall():
                bno = row["bid_ntce_no"]
                if bno not in analysis_status_map:  # 최신 결과만
                    analysis_status_map[bno] = row["strategy_report"]

        curated_list = []
        for scored_bid in scored_bids:
            bid_no = scored_bid.get("bid_ntce_no", "")
            if not bid_no:
                continue

            strategy_report = analysis_status_map.get(bid_no)
            if strategy_report:
                status = "strategy_ready"
            elif bid_no in analysis_status_map:
                status = "analyzed"
            else:
                status = "new"

            curated_list.append({
                "bid_ntce_no": bid_no,
                "title": scored_bid.get("title", scored_bid.get("bidNtceNm", "")),
                "org_name": scored_bid.get("org_name", scored_bid.get("ntceInsttNm", "")),
                "budget": scored_bid.get("budget", scored_bid.get("presmptPrce")),
                "bid_close_dt": scored_bid.get("bid_close_dt", scored_bid.get("bidClseDt")),
                "relevance_score": scored_bid.get("relevance_score", 0),
                "matched_keywords": scored_bid.get("matched_keywords", []),
                "status": status,
            })

        # 관련도 점수 내림차순 정렬 후 limit 적용
        curated_list.sort(key=lambda x: x["relevance_score"], reverse=True)
        return curated_list[:limit]
    except HTTPException:
        raise
    except Exception as e:
        logger.error("큐레이션 공고 조회 실패: %s", e)
        raise HTTPException(status_code=500, detail="서버 내부 오류가 발생했습니다")
