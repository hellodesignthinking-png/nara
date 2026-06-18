"""
분석 API 라우트

/analyze, /analyses/*, /analyze-strategy 엔드포인트:
전체 분석 파이프라인, 결과 조회/삭제, 실시간 전략 분석
"""

import asyncio
import concurrent.futures
import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from src.config import load_config
from src.models.schemas import AnalysisResult
from src.models.database import DatabaseManager
from src.analyzers.biz_matcher import BizMatcher
from src.analyzers.llm_analyzer import LLMAnalyzer
from src.analyzers.strategy_engine import StrategyEngine
from src.analyzers.proposal_strategy import ProposalStrategyAnalyzer

# 선택적 의존성: 설치되지 않았을 경우 None으로 대체
try:
    from src.analyzers.vector_store import VectorStore
except ImportError:
    VectorStore = None

from ._helpers import (
    get_db,
    get_active_company,
    get_optional_active_company,
    get_current_user,
    _analysis_to_api_dict,
    _bid_to_matcher_dict,
    _biz_profile_to_matcher_dict,
    _load_settings,
)
from ._models import StrategyAnalysisRequest, ProposalStrategyRequest, AnalysisChatRequest

logger = logging.getLogger(__name__)

router = APIRouter(tags=["analyses"])


# ──────────────────────────────────────────────
# 분석 API
# ──────────────────────────────────────────────


@router.post("/analyze", summary="참여 가능 공고 분석")
async def run_full_analysis(
    active_biz_id: Optional[str] = Depends(get_optional_active_company),
    username: str = Depends(get_current_user),
    db: DatabaseManager = Depends(get_db)
):
    """
    DB에 수집된 공고를 분석하여 참여 가능한 공고를 분류합니다.

    실행 흐름:
    1. DB에서 최근 수집된 공고 로드
    2. 등록된 사업자 프로필과 매칭 점수 계산 (업종/면허/예산/지역/실적)
    3. 참여 가능(매칭 40점 이상) 공고만 필터링
    4. (선택) LLM 전략 보고서 생성
    5. 결과를 DB에 저장하고 반환

    Returns:
        total_bids: 분석 대상 전체 공고 수
        participable: 참여 가능 공고 수
        analyzed: 분석 완료된 공고 수
        results: 분석 결과 상세 리스트
    """
    try:
        config = load_config()

        # ── 1단계: DB에서 최근 수집 공고 로드 ──
        logger.info("📋 분석: 1단계 - 수집된 공고 로드")
        bids = db.get_recent_bids(limit=500)

        if not bids:
            return {
                "total_bids": 0,
                "participable": 0,
                "analyzed": 0,
                "results": [],
                "message": "수집된 공고가 없습니다. 먼저 공고를 수집해주세요.",
            }

        # ── 2단계: 사업자 로드 ──
        logger.info("🏢 분석: 2단계 - 사업자 프로필 로드 (%s)", active_biz_id)
        biz_profile = db.get_business(active_biz_id) if active_biz_id else None
        ai_settings = db.get_user_ai_settings(username)

        if not biz_profile:
            return {
                "total_bids": len(bids),
                "participable": 0,
                "analyzed": 0,
                "results": [],
                "message": "활성화된 회사 프로필을 찾을 수 없습니다. 먼저 회사를 등록해주세요.",
            }

        # ── 3단계: 사업자-공고 매칭 (참여 가능성 평가) ──
        logger.info("🎯 분석: 3단계 - 참여 가능 공고 필터링")
        biz_dicts = [_biz_profile_to_matcher_dict(biz_profile)]
        bid_dicts = [_bid_to_matcher_dict(b) for b in bids]

        biz_matcher = BizMatcher()
        match_results = biz_matcher.match_all_bids(biz_dicts, bid_dicts, ai_settings)

        # 매칭 점수 40점 이상만 "참여 가능" 으로 분류
        MIN_MATCH_SCORE = 40
        participable = [
            r for r in match_results
            if r.get("best_match", {}).get("score", 0) >= MIN_MATCH_SCORE
        ]

        logger.info(
            "🎯 매칭 완료: 전체 %d건 → 참여 가능 %d건 (기준: %d점 이상)",
            len(bids), len(participable), MIN_MATCH_SCORE
        )

        if not participable:
            return {
                "total_bids": len(bids),
                "participable": 0,
                "analyzed": 0,
                "results": [],
                "message": f"매칭 점수 {MIN_MATCH_SCORE}점 이상인 참여 가능 공고가 없습니다.",
            }

        # ── 4단계: AI 전략 보고서 생성 (참여 가능 공고만) ──
        logger.info("🤖 분석: 4단계 - AI 전략 보고서 (%d건)", len(participable))
        user_settings = _load_settings()
        llm_engine = user_settings.get('llm_engine', getattr(config, 'llm_engine', 'gemini'))
        if llm_engine == "gemini":
            llm_analyzer = LLMAnalyzer(
                api_key=getattr(config, "gemini_api_key", ""),
                model=getattr(config, "gemini_model", "gemini-2.5-flash"),
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
        for result in participable:
            bid = result["bid"]
            best_match = result.get("best_match") or {}
            business = best_match.get("business", {})
            match_score = best_match.get("score", 0)
            match_details = best_match.get("details", {})

            try:
                # 과거 낙찰 정보 조회
                past_awards_for_bid = []
                try:
                    bid_title_kw = bid.get('title', '')[:20]
                    if bid_title_kw:
                        existing = db.get_awards_by_title(bid_title_kw)
                        past_awards_for_bid = [
                            aw.to_dict() if hasattr(aw, 'to_dict') else aw
                            for aw in (existing or [])[:10]
                        ]
                except Exception:
                    pass

                strategy = await asyncio.to_thread(
                    strategy_engine.generate_strategy,
                    bid=bid,
                    business_profile=business,
                    rfp_text=bid.get("rfp_text", ""),
                    past_awards=past_awards_for_bid,
                    news_articles=[],
                )

                # DB에 분석 결과 저장
                analysis = AnalysisResult(
                    bid_ntce_no=bid.get("bid_ntce_no", ""),
                    biz_id=business.get("biz_id", ""),
                    relevance_score=match_details.get("license_score", 0) + match_details.get("keyword_score", 0) + match_details.get("region_score", 0),
                    match_score=match_score,
                    summary=strategy.get("bid_summary", ""),
                    strategy_report=json.dumps(strategy, ensure_ascii=False, default=str),
                    competitors=strategy.get("competitor_analysis", ""),
                )
                db.save_analysis(analysis)

                final_results.append({
                    "bid_ntce_no": bid.get("bid_ntce_no", ""),
                    "bid_title": bid.get("title", bid.get("bidNtceNm", "")),
                    "org_name": bid.get("org_name", bid.get("ntceInsttNm", "")),
                    "budget": bid.get("budget"),
                    "bid_close_dt": bid.get("bid_close_dt", ""),
                    "match_score": match_score,
                    "match_reasons": match_details,
                    "matched_business": business.get("company_name", business.get("name", "")),
                    "recommendation": best_match.get("recommendation", ""),
                    "strategy_summary": strategy.get("bid_summary", ""),
                    "overall_recommendation": strategy.get("overall_recommendation", ""),
                    "participable": True,
                })

            except Exception as e:
                logger.warning("전략 보고서 생성 실패 (%s): %s", bid.get("title", ""), e)
                final_results.append({
                    "bid_ntce_no": bid.get("bid_ntce_no", ""),
                    "bid_title": bid.get("title", bid.get("bidNtceNm", "")),
                    "org_name": bid.get("org_name", ""),
                    "budget": bid.get("budget"),
                    "match_score": match_score,
                    "matched_business": business.get("company_name", ""),
                    "participable": True,
                    "error": "전략 분석에 실패했습니다. 다시 시도해주세요.",
                })

        # 매칭 점수 높은 순으로 정렬
        final_results.sort(key=lambda x: x.get("match_score", 0), reverse=True)

        logger.info("✅ 분석 완료: 참여 가능 %d건 분석", len(final_results))
        return {
            "total_bids": len(bids),
            "participable": len(participable),
            "analyzed": len(final_results),
            "results": final_results,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("분석 파이프라인 실패: %s", e)
        raise HTTPException(status_code=500, detail="서버 내부 오류가 발생했습니다")


@router.get("/analyses", summary="분석 결과 목록 조회")
async def get_analyses(
    bid_ntce_no: Optional[str] = Query(None, description="공고번호 필터"),
    biz_id: Optional[str] = Query(None, description="사업자번호 필터"),
    active_biz_id: str = Depends(get_optional_active_company),
    db: DatabaseManager = Depends(get_db),
):
    """
    분석 결과 목록을 조회합니다.

    bid_ntce_no 또는 biz_id로 필터링할 수 있습니다.
    필터가 없으면 활성화된 회사의 최근 분석 결과 전체를 반환합니다.
    """
    if not active_biz_id:
        return []
    try:
        # 안전한 격리: 다른 회사 데이터를 요청 시 권한 체크 또는 강제 교체
        target_biz_id = biz_id if biz_id else active_biz_id
        if target_biz_id != active_biz_id:
            target_biz_id = active_biz_id

        if bid_ntce_no:
            conn = db.get_connection()
            cursor = conn.execute(
                "SELECT * FROM analysis_results WHERE bid_ntce_no = ? AND biz_id = ?",
                (bid_ntce_no, target_biz_id),
            )
            results = [
                AnalysisResult.from_dict(dict(row))
                for row in cursor.fetchall()
            ]
        else:
            conn = db.get_connection()
            cursor = conn.execute(
                """
                SELECT * FROM analysis_results
                WHERE biz_id = ?
                ORDER BY analyzed_at DESC
                LIMIT 100
                """,
                (target_biz_id,)
            )
            results = [
                AnalysisResult.from_dict(dict(row))
                for row in cursor.fetchall()
            ]

        # 중복 제거 (같은 공고번호의 최신 분석만)
        seen = set()
        unique = []
        for r in results:
            if r.bid_ntce_no not in seen:
                seen.add(r.bid_ntce_no)
                unique.append(r)

        # 배치 쿼리: 공고 정보
        bid_nos = [r.bid_ntce_no for r in unique]
        bid_map = {}
        if bid_nos:
            conn = db.get_connection()
            placeholders = ",".join("?" for _ in bid_nos)
            cursor = conn.execute(
                f"SELECT * FROM bid_announcements WHERE bid_ntce_no IN ({placeholders})",
                bid_nos,
            )
            for row in cursor.fetchall():
                bid_map[row["bid_ntce_no"]] = dict(row)

        # 배치 쿼리: 사업자 정보
        biz_ids = list({r.biz_id for r in unique if r.biz_id})
        biz_map = {}
        if biz_ids:
            placeholders = ",".join("?" for _ in biz_ids)
            cursor = conn.execute(
                f"SELECT biz_id, company_name FROM business_profiles WHERE biz_id IN ({placeholders})",
                biz_ids,
            )
            for row in cursor.fetchall():
                biz_map[row["biz_id"]] = row["company_name"]

        enriched = []
        for r in unique:
            d = _analysis_to_api_dict(r)
            bid_row = bid_map.get(r.bid_ntce_no)
            if bid_row:
                d["bid_title"] = bid_row.get("title") or r.bid_ntce_no
                d["org_name"] = bid_row.get("org_name") or ""
                d["budget"] = bid_row.get("budget") or 0
                d["bid_close_dt"] = bid_row.get("bid_close_dt") or ""
            else:
                d["bid_title"] = r.bid_ntce_no
                d["org_name"] = ""
                d["budget"] = 0
            if r.biz_id:
                d["company_name"] = biz_map.get(r.biz_id, "")
            enriched.append(d)

        return enriched
    except HTTPException:
        raise
    except Exception as e:
        logger.error("분석 결과 목록 조회 실패: %s", e)
        raise HTTPException(status_code=500, detail="서버 내부 오류가 발생했습니다")


@router.get("/analyses/recurring-forecast", summary="연간 반복 사업 발주 예측")
async def get_recurring_forecast(db: DatabaseManager = Depends(get_db)):
    """
    과거 수집된 입찰 공고를 정밀 분석하여 매년 정기적으로 반복 발주되는 사업을 예측합니다.
    """
    try:
        # DB에서 최근 500건의 입찰 공고 로드
        bids = db.get_recent_bids(limit=500)
        if not bids:
            return []

        # 제목 정규화 및 그룹화
        import re
        from collections import defaultdict
        
        # 연도를 식별하기 위한 정규식
        year_pat = re.compile(r'20\d{2}년?|\[긴급\]|\[재공고\]')
        
        groups = defaultdict(list)
        for bid in bids:
            title = bid.title
            if not title:
                continue
            # 연도 및 상태 수식어 제거하여 표준 사업명 획득
            norm_title = year_pat.sub('', title).strip()
            norm_title = re.sub(r'\s+', ' ', norm_title) # 중복 공백 제거
            
            # 발주기관명과 결합하여 고유 사업 키 정의 (이름이 유사하고 기관이 같아야 함)
            key = (norm_title, bid.org_name or '')
            groups[key].append(bid)
            
        forecast_results = []
        for (norm_title, org_name), bid_list in groups.items():
            # 연도별로 최소 2회 이상 정기 발주된 사업만 연간 반복 사업으로 판단
            if len(bid_list) < 2:
                continue
                
            # 발주월(Month) 통계 내기
            months = []
            budgets = []
            for b in bid_list:
                if b.bid_close_dt:
                    try:
                        month = int(b.bid_close_dt.split('-')[1])
                        months.append(month)
                    except Exception:
                        pass
                if b.budget:
                    budgets.append(b.budget)
                    
            if not months:
                continue
                
            # 예측 발주월 (가장 빈도가 높은 달 또는 평균 달)
            pred_month = int(sum(months) / len(months))
            avg_budget = int(sum(budgets) / len(budgets)) if budgets else 0
            
            # D-Day 계산 (2026년 기준 다가오는 예상 시기 계산)
            from datetime import datetime
            current_date = datetime.now()
            current_year = current_date.year
            current_month = current_date.month
            
            # 예측월이 올해 이미 지났으면 내년으로 설정
            pred_year = current_year
            if pred_month < current_month:
                pred_year = current_year + 1
                
            try:
                pred_date = datetime(pred_year, pred_month, 15) # 매월 중순으로 가정
                days_left = (pred_date - current_date).days
            except Exception:
                days_left = 30 # 예외 발생 시 디폴트 값
                
            # 예산 포맷팅
            budget_str = f"{avg_budget // 10000:,}만 원" if avg_budget else "정보 없음"
            
            forecast_results.append({
                "original_title": bid_list[0].title,
                "predicted_title": f"{pred_year}년 {norm_title}",
                "org_name": org_name,
                "avg_budget": avg_budget,
                "budget_str": budget_str,
                "expected_month": pred_month,
                "probability": min(75 + len(bid_list) * 5, 95), # 반복 횟수에 비례한 신뢰도
                "days_left": max(1, days_left),
                "frequency": len(bid_list)
            })
            
        # 남은 일수가 가까운 순으로 정렬
        forecast_results.sort(key=lambda x: x["days_left"])
        
        # 상위 5개 알짜 예측 리스트만 반환
        return forecast_results[:5]

    except Exception as e:
        logger.error("연간 반복 사업 발주 예측 실패: %s", e)
        return []


@router.get("/analyses/competitor-intelligence", summary="경쟁사 수주 타깃 분석")
async def get_competitor_intelligence(limit: int = 5, db: DatabaseManager = Depends(get_db)):
    """
    최근 낙찰 정보를 기반으로 경쟁사들의 수주 현황 및 투찰 통계를 분석해 반환합니다.
    """
    try:
        stats = db.get_competitor_market_share(limit=limit)
        return stats
    except Exception as e:
        logger.error("경쟁사 수주 타깃 분석 실패: %s", e)
        return []


@router.get("/analyses/{analysis_id}", summary="분석 결과 상세 조회")
async def get_analysis_detail(analysis_id: int, db: DatabaseManager = Depends(get_db)):
    """
    분석 결과 ID로 상세 정보(전략 보고서 포함)를 조회합니다.

    strategy_report 필드에는 JSON 형태의 전략 보고서 전문이 포함됩니다.
    """
    try:
        conn = db.get_connection()
        cursor = conn.execute(
            "SELECT * FROM analysis_results WHERE id = ?",
            (analysis_id,),
        )
        row = cursor.fetchone()
        if not row:
            raise HTTPException(
                status_code=404,
                detail=f"분석 결과를 찾을 수 없습니다: ID={analysis_id}",
            )

        result = AnalysisResult.from_dict(dict(row))
        api_dict = _analysis_to_api_dict(result)

        # strategy_report가 JSON 문자열이면 파싱하여 반환
        if api_dict.get("strategy_report"):
            try:
                api_dict["strategy_report"] = json.loads(api_dict["strategy_report"])
            except (json.JSONDecodeError, TypeError):
                pass  # 파싱 실패 시 원본 문자열 유지

        return api_dict
    except HTTPException:
        raise
    except Exception as e:
        logger.error("분석 결과 상세 조회 실패: %s", e)
        raise HTTPException(status_code=500, detail="서버 내부 오류가 발생했습니다")


@router.get("/analyses/{analysis_id}/full", summary="분석 결과 전체 조회 (AI 요약 포함)")
async def get_analysis_full(analysis_id: int, db: DatabaseManager = Depends(get_db)):
    """
    분석 결과 ID로 전체 정보를 조회합니다.
    strategy_report, summary, competitors 등 모든 필드를 파싱된 형태로 반환합니다.
    프론트엔드의 AI 요약 버튼이 호출하는 엔드포인트입니다.
    """
    try:
        conn = db.get_connection()
        cursor = conn.execute(
            "SELECT * FROM analysis_results WHERE id = ?",
            (analysis_id,),
        )
        row = cursor.fetchone()
        if not row:
            raise HTTPException(
                status_code=404,
                detail=f"분석 결과를 찾을 수 없습니다: ID={analysis_id}",
            )

        result = AnalysisResult.from_dict(dict(row))
        api_dict = _analysis_to_api_dict(result)

        # strategy_report가 JSON 문자열이면 파싱하여 반환
        if api_dict.get("strategy_report"):
            try:
                api_dict["strategy_report"] = json.loads(api_dict["strategy_report"])
            except (json.JSONDecodeError, TypeError):
                pass

        # 연관된 입찰공고 정보를 함께 반환
        bid_no = api_dict.get("bid_ntce_no")
        if bid_no:
            bid_cursor = conn.execute(
                "SELECT * FROM bid_announcements WHERE bid_ntce_no = ?",
                (bid_no,),
            )
            bid_row = bid_cursor.fetchone()
            if bid_row:
                from src.models.schemas import BidAnnouncement
                from ._helpers import _bid_to_api_dict
                bid_obj = BidAnnouncement.from_dict(dict(bid_row))
                api_dict["bid_detail"] = _bid_to_api_dict(bid_obj)

        # 연관된 사업자 정보를 함께 반환
        biz_id = api_dict.get("biz_id")
        if biz_id:
            biz_cursor = conn.execute(
                "SELECT company_name FROM business_profiles WHERE biz_id = ?",
                (biz_id,),
            )
            biz_row = biz_cursor.fetchone()
            if biz_row:
                api_dict["company_name"] = biz_row["company_name"]

        api_dict["analysis_summary"] = _generate_analysis_summary(api_dict)

        return api_dict
    except HTTPException:
        raise
    except Exception as e:
        logger.error("분석 결과 전체 조회 실패: %s", e)
        raise HTTPException(status_code=500, detail="서버 내부 오류가 발생했습니다")


def _generate_analysis_summary(analysis: dict) -> str:
    """분석 결과 데이터에서 사람이 읽을 수 있는 AI 요약을 자동 생성합니다."""
    parts = []
    
    score = analysis.get("match_score") or analysis.get("relevance_score") or 0
    if score >= 70:
        parts.append(f"✅ 높은 매칭도({score:.0f}점)로 적극 참여가 권장됩니다.")
    elif score >= 45:
        parts.append(f"⚠️ 보통 수준의 매칭도({score:.0f}점)로, 보완 사항을 확인한 후 참여를 검토하세요.")
    else:
        parts.append(f"❌ 낮은 매칭도({score:.0f}점)로 신중한 검토가 필요합니다.")
    
    summary = analysis.get("summary")
    if summary:
        parts.append(f"📋 요약: {summary}")
    
    competitors = analysis.get("competitors")
    if competitors and isinstance(competitors, list) and len(competitors) > 0:
        parts.append(f"🏢 주요 경쟁사: {', '.join(str(c) for c in competitors[:3])}")
    
    return " | ".join(parts) if parts else "분석 결과를 불러왔습니다."


@router.delete("/analyses/{analysis_id}", summary="분석 결과 삭제")
async def delete_analysis(analysis_id: int, db: DatabaseManager = Depends(get_db)):
    """분석 결과를 삭제합니다."""
    try:
        deleted = db.delete_analysis(analysis_id)
        if not deleted:
            raise HTTPException(
                status_code=404,
                detail=f"분석 결과를 찾을 수 없습니다: ID={analysis_id}",
            )
        return {"message": f"분석 결과 삭제 완료 (ID: {analysis_id})"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("분석 결과 삭제 실패: %s", e)
        raise HTTPException(status_code=500, detail="서버 내부 오류가 발생했습니다")


@router.delete("/analyses", summary="분석 결과 전체 삭제")
async def delete_all_analyses(db: DatabaseManager = Depends(get_db)):
    """모든 분석 결과를 삭제합니다."""
    try:
        count = db.delete_all_analyses()
        return {"message": f"분석 결과 {count}건 삭제 완료", "deleted": count}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("분석 결과 전체 삭제 실패: %s", e)
        raise HTTPException(status_code=500, detail="서버 내부 오류가 발생했습니다")


# ──────────────────────────────────────────────
# 실시간 전략 분석 API
# ──────────────────────────────────────────────


@router.post("/analyze-strategy", summary="실시간 전략 분석")
async def analyze_strategy(
    request: StrategyAnalysisRequest, 
    username: str = Depends(get_current_user), 
    db: DatabaseManager = Depends(get_db)
):
    """
    단일 공고에 대한 실시간 전략 분석을 수행합니다.

    공고번호로 DB에서 공고를 불러온 후 과거 낙찰 데이터·뉴스를 수집하고,
    등록된 사업자 중 최적 매칭 대상을 선정하여 전략 보고서를 생성합니다.
    OpenAI 키가 없으면 폴백 모드로 동작합니다.

    Args:
        request: 분석 대상 공고번호를 포함한 요청 본문

    Returns:
        전략 보고서 전체 (bid_info, bid_summary, strategy_report 등)
    """
    try:
        config = load_config()

        # ── 1단계: 공고 로드 ──
        bid = db.get_bid_by_no(request.bid_ntce_no)
        if not bid:
            raise HTTPException(
                status_code=404,
                detail=f"공고를 찾을 수 없습니다: {request.bid_ntce_no}",
            )

        bid_dict = _bid_to_matcher_dict(bid)
        bid_title = bid.title or ""
        org_name = bid.org_name or ""

        # ── 2단계: 등록 사업자 로드 ──
        biz_profiles = db.get_businesses(username)
        ai_settings = db.get_user_ai_settings(username)

        best_match = {}
        business = {}
        match_score = 0.0
        match_results = []

        if biz_profiles:
            # 최적 사업자 매칭
            biz_dicts = [_biz_profile_to_matcher_dict(bp) for bp in biz_profiles]
            biz_matcher = BizMatcher()
            match_results = biz_matcher.match_all_bids(biz_dicts, [bid_dict], ai_settings)
            if match_results:
                best_match = match_results[0].get("best_match") or {}
                business = best_match.get("business", {})
                match_score = best_match.get("score", 0.0)
        else:
            logger.info("등록된 사업자 없음 — 범용 분석 모드로 실행")

        # OpenAI 키 없으면 외부 수집 스킵 (폴백 모드 즉시 응답)
        # LLM 엔진 선택: settings.json 또는 .env의 LLM_ENGINE 사용
        user_settings = _load_settings()
        llm_engine = user_settings.get("llm_engine", getattr(config, "llm_engine", "gemini"))

        if llm_engine == "gemini":
            has_llm = bool(getattr(config, "gemini_api_key", ""))
            llm_api_key = getattr(config, "gemini_api_key", "")
            llm_model = getattr(config, "gemini_model", "gemini-2.5-flash")
        else:
            has_llm = bool(config.openai_api_key)
            llm_api_key = config.openai_api_key or ""
            llm_model = config.openai_model

        # ── 3단계: 과거 낙찰 정보 수집 (공공데이터포털 API) ──
        past_award_dicts = []
        try:
            # DB에 이미 저장된 낙찰 데이터가 있으면 먼저 활용
            existing_awards = db.get_awards_by_title(bid_title[:20]) if bid_title else []
            past_award_dicts = [
                aw.to_dict() if hasattr(aw, "to_dict") else aw
                for aw in (existing_awards or [])
            ]
        except Exception:
            pass

        # DB에 없으면 공공데이터포털 API로 실시간 수집
        if not past_award_dicts and getattr(config, 'data_go_kr_api_key', ''):
            try:
                from src.collectors.award_collector import AwardCollector
                award_collector = AwardCollector(config)
                # 공고 제목에서 핵심 키워드 추출 (앞 3단어)
                search_kw = ' '.join(bid_title.split()[:3]) if bid_title else ''
                if search_kw:
                    awards = award_collector.collect_awards_by_keyword(search_kw, years_back=2)
                    past_award_dicts = [
                        aw.to_dict() if hasattr(aw, "to_dict") else aw
                        for aw in (awards or [])[:10]
                    ]
                    logger.info("과거 낙찰정보 %d건 수집 완료 (키워드: %s)", len(past_award_dicts), search_kw)
                award_collector.close()
            except Exception as e:
                logger.warning("낙찰정보 수집 실패 (무시): %s", e)

        # ── 4단계: 관련 뉴스 수집 (네이버 검색 API) ──
        news_dicts = []
        if getattr(config, 'naver_client_id', '') and getattr(config, 'naver_client_secret', ''):
            try:
                from src.collectors.news_collector import NewsCollector
                news_collector = NewsCollector(config)
                # 발주기관 + 사업 키워드로 뉴스 검색
                kw_list = [bid_title.split()[0]] if bid_title and bid_title.split() else None
                news_articles = news_collector.collect_org_news(
                    org_name=org_name,
                    keywords=kw_list,
                    years_back=1,
                )
                news_dicts = [
                    {
                        'title': n.title,
                        'description': n.description,
                        'date': n.pub_date,
                        'link': n.link,
                    }
                    for n in (news_articles or [])[:10]
                ]
                logger.info("관련 뉴스 %d건 수집 완료 (기관: %s)", len(news_dicts), org_name)
                news_collector.close()
            except Exception as e:
                logger.warning("뉴스 수집 실패 (무시): %s", e)

        # ── 5단계: 전략 보고서 생성 (120초 타임아웃) ──
        if has_llm:
            try:

                def _generate_strategy():
                    llm_analyzer = LLMAnalyzer(
                        api_key=llm_api_key,
                        model=llm_model,
                        engine=llm_engine,
                    )
                    strategy_engine = StrategyEngine(llm_analyzer)
                    return strategy_engine.generate_strategy(
                        bid=bid_dict,
                        business_profile=business,
                        rfp_text=bid.rfp_text or "",
                        past_awards=past_award_dicts,
                        news_articles=news_dicts,
                    )
                loop = asyncio.get_running_loop()
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    strategy = await asyncio.wait_for(
                        loop.run_in_executor(pool, _generate_strategy), timeout=120.0
                    )
            except (asyncio.TimeoutError, Exception) as e:
                logger.warning("LLM 전략 생성 실패/타임아웃, 폴백 모드 사용: %s", e)
                has_llm = False  # 아래 폴백으로 진행

        if not has_llm:
            # 폴백: LLM 없이 기본 정보만 구성 (즉시 응답)
            budget_text = f"{bid.budget:,.0f}원" if bid.budget else "미공개"
            strategy = {
                "bid_info": {
                    "title": bid_title,
                    "organization": org_name,
                    "budget": bid.budget,
                    "deadline": bid.bid_close_dt,
                },
                "bid_summary": f"## 📋 공고 요약\n\n**{bid_title}**\n\n- 발주기관: {org_name}\n- 추정가격: {budget_text}\n- 마감일: {bid.bid_close_dt or '미정'}\n\n> 💡 Gemini 또는 OpenAI API 키를 설정하면 AI 기반 상세 전략 분석이 가능합니다.\n> 설정 → API 키 관리에서 키를 입력해주세요.",
                "competitor_analysis": "### 경쟁 분석\n\nGemini 또는 OpenAI API 키를 설정하면 경쟁사 분석이 제공됩니다.\n\n- 예상 입찰 업체 수\n- 과거 유사 공고 낙찰 현황\n- 경쟁 강도 평가",
                "differentiation_strategy": "### 차별화 전략\n\nGemini 또는 OpenAI API 키를 설정하면 맞춤형 차별화 전략이 제공됩니다.\n\n- 기술 제안 차별화 포인트\n- 가격 전략 제안\n- 발주처 니즈 분석",
                "proposal_outline": "### 제안서 기획\n\nGemini 또는 OpenAI API 키를 설정하면 제안서 구조와 핵심 전략이 제공됩니다.",
                "risk_factors": "",
                "budget_analysis": "",
                "action_items": [
                    "설정 페이지에서 Gemini 또는 OpenAI API 키를 입력하세요",
                    "나라장터에서 공고 상세 내용을 확인하세요",
                    f"마감일({bid.bid_close_dt or '미정'})을 캘린더에 등록하세요"
                ],
                "overall_recommendation": "AI 분석을 위해 Gemini 또는 OpenAI API 키를 설정해주세요.",
                "metadata": {"analysis_engine": "fallback"},
            }

        # ── 6단계: VectorStore 컨텍스트 추가 (선택) ──
        if VectorStore is not None:
            try:
                vector_store = VectorStore()
                vector_store.add_bid_context(
                    bid_no=request.bid_ntce_no,
                    rfp_text=bid.rfp_text or bid_title,
                    news_articles=news_dicts,
                    past_awards=past_award_dicts,
                )
            except Exception as e:
                logger.debug("VectorStore 컨텍스트 저장 스킵: %s", e)

        # ── 7단계: DB에 분석 결과 저장 ──
        try:
            analysis = AnalysisResult(
                bid_ntce_no=request.bid_ntce_no,
                biz_id=business.get("biz_id", ""),
                relevance_score=match_results[0].get("relevance_score", 0) if match_results else 0,
                match_score=match_score,
                summary=strategy.get("bid_summary", ""),
                strategy_report=json.dumps(strategy, ensure_ascii=False, default=str),
                competitors=strategy.get("competitor_analysis", ""),
            )
            db.save_analysis(analysis)
        except Exception as e:
            logger.warning("분석 결과 DB 저장 실패: %s", e)

        return {
            "bid_ntce_no": request.bid_ntce_no,
            "bid_title": bid_title,
            "org_name": org_name,
            "matched_business": business.get("company_name", business.get("name", "")),
            "match_score": match_score,
            "strategy": strategy,
            "past_awards_count": len(past_award_dicts),
            "news_count": len(news_dicts),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("실시간 전략 분석 실패: %s", e)
        raise HTTPException(status_code=500, detail="서버 내부 오류가 발생했습니다")


@router.post("/analyze-proposal-strategy", summary="제안서 고도화 전략 분석")
async def analyze_proposal_strategy(request: ProposalStrategyRequest, db: DatabaseManager = Depends(get_db)):
    """
    제안서 고도화 전략 분석 API

    기존 /analyze-strategy보다 심층적인 분석을 제공합니다:
    - 경쟁사 수주 패턴 분석
    - 발주기관 정책 방향 분석
    - 지역 트렌드 분석
    - 투찰률 최적화
    - RFP 전년 대비 변화 분석
    - LLM 기반 종합 전략 보고서
    """
    try:
        config = load_config()

        # 공고 존재 확인
        bid = db.get_bid_by_no(request.bid_ntce_no)
        if not bid:
            raise HTTPException(
                status_code=404,
                detail=f"공고를 찾을 수 없습니다: {request.bid_ntce_no}",
            )

        # ProposalStrategyAnalyzer 실행 (타임아웃 180초)
        def _run_analysis():
            analyzer = ProposalStrategyAnalyzer(db=db, config=config)
            return analyzer.generate_proposal_strategy(
                bid_ntce_no=request.bid_ntce_no,
                biz_id=request.biz_id,
            )

        loop = asyncio.get_running_loop()
        with concurrent.futures.ThreadPoolExecutor() as pool:
            result = await asyncio.wait_for(
                loop.run_in_executor(pool, _run_analysis),
                timeout=180.0,
            )

        # 프론트엔드 renderProposalStrategy()가 기대하는 형태로 변환
        bid_info = result.get("bid_info", {})
        business = result.get("business_profile", {})

        # 경쟁사 분석 결과 → competitor_intelligence
        competitor_raw = result.get("competitor_analysis", {})
        competitor_intelligence = {
            "top_competitors": [
                {
                    "company_name": c.get("name", ""),
                    "win_count": c.get("win_count", 0),
                    "avg_bid_rate": c.get("avg_bid_rate", 0),
                    "total_amount": c.get("avg_award_amount", 0),
                }
                for c in competitor_raw.get("top_competitors", [])
            ],
            "market_concentration": competitor_raw.get("market_concentration", {}),
            "our_competitive_position": (
                f"{business.get('company_name', '귀사')}는 "
                f"총 {competitor_raw.get('competitive_position', {}).get('total_competitors', 0)}개 경쟁사 중 "
                f"차별화 전략이 필요합니다."
            ),
        }

        # 발주기관 정책
        org_raw = result.get("org_policy", {})
        org_policy_analysis = {}
        if not org_raw.get("error"):
            policy_direction_parts = []
            if org_raw.get("total_bids"):
                policy_direction_parts.append(
                    f"{org_raw.get('org_name', '')}은 총 {org_raw['total_bids']}건의 공고를 발주했습니다."
                )
            top_cats = org_raw.get("top_categories", [])
            if top_cats:
                cat_names = ", ".join(c["category"] for c in top_cats[:3])
                policy_direction_parts.append(f"주력 분야: {cat_names}")
            org_policy_analysis = {
                "policy_direction": " ".join(policy_direction_parts) if policy_direction_parts else None,
                "preferred_vendors_insight": (
                    ", ".join(
                        f"{v['name']}({v['win_count']}건)"
                        for v in org_raw.get("preferred_vendors", [])[:5]
                    )
                    if org_raw.get("preferred_vendors")
                    else None
                ),
                "recurring_project_insight": (
                    f"이 기관은 연간 평균 투찰률 {org_raw.get('award_stats', {}).get('avg_bid_rate', 0):.1f}%로, "
                    f"총 {org_raw.get('total_awards', 0)}건의 낙찰 이력이 있습니다."
                    if org_raw.get("total_awards", 0) > 0
                    else None
                ),
            }

        # 지역 트렌드
        region_raw = result.get("regional_trend", {})
        regional_analysis = {}
        if not region_raw.get("error"):
            market_overview = region_raw.get("market_overview", {})
            market_trend = None
            if market_overview.get("total_awards"):
                market_trend = (
                    f"{region_raw.get('region', '')} 지역에서 총 {market_overview['total_awards']}건의 "
                    f"낙찰이 있었으며, 평균 낙찰금액은 {market_overview.get('avg_award_amount', 0):,}원입니다."
                )
            pa = region_raw.get("policy_alignment", {})
            regional_analysis = {
                "market_trend": market_trend,
                "policy_alignment": pa.get("recommendation"),
                "local_preference": region_raw.get("local_preference", {}).get("recommendation"),
            }

        # 투찰률 최적화
        rate_raw = result.get("bid_rate_optimization", {})
        bid_rate_recommendation = {}
        if not rate_raw.get("error"):
            rec = rate_raw.get("recommended_rate", {})
            bid_rate_recommendation = {
                "optimal_rate": rec.get("optimal"),
                "range": [rec.get("range_low", 85), rec.get("range_high", 91)],
                "confidence": rec.get("confidence", 0),
                "rationale": rate_raw.get("risk_assessment", {}).get("strategy", ""),
            }

        # RFP 변화
        rfp_raw = result.get("rfp_changes", {})
        rfp_change_analysis = {}
        if rfp_raw.get("diff_summary"):
            diff = rfp_raw["diff_summary"]
            rfp_change_analysis = {
                "vs_last_year": (
                    f"전년 대비 유사도 {diff.get('similarity_ratio', 0) * 100:.1f}%, "
                    f"변경 {diff.get('changed_count', 0)}건 "
                    f"(추가 {diff.get('added_count', 0)}, 삭제 {diff.get('removed_count', 0)})"
                ),
                "new_requirements": [
                    c.get("content", str(c))
                    for c in rfp_raw.get("key_changes", [])
                    if isinstance(c, dict) and c.get("type") == "added"
                ][:10],
            }
        elif rfp_raw.get("note"):
            rfp_change_analysis = {"vs_last_year": rfp_raw["note"]}

        # LLM 전략 보고서
        llm_raw = result.get("llm_strategy_report", {})

        # 매칭 점수 계산 (분석 결과 풍부도 기반)
        _score = 30  # 기본점
        if competitor_intelligence.get("top_competitors"):
            _score += min(len(competitor_intelligence["top_competitors"]) * 5, 15)
        if org_policy_analysis.get("policy_direction"):
            _score += 10
        if regional_analysis.get("market_trend"):
            _score += 10
        if bid_rate_recommendation.get("optimal_rate"):
            _score += 10
            if bid_rate_recommendation.get("confidence", 0) > 0.5:
                _score += 5
        if rfp_change_analysis.get("vs_last_year"):
            _score += 10
        if llm_raw.get("proposal_outline"):
            _score += 10
        _match_score = min(_score, 100)

        # 최종 응답
        return {
            "bid_title": bid_info.get("title", ""),
            "org_name": bid_info.get("org_name", ""),
            "matched_business": business.get("company_name", ""),
            "match_score": _match_score,
            "strategy": {
                "competitor_intelligence": competitor_intelligence if competitor_intelligence.get("top_competitors") else None,
                "org_policy_analysis": org_policy_analysis if org_policy_analysis.get("policy_direction") else None,
                "regional_analysis": regional_analysis if regional_analysis.get("market_trend") or regional_analysis.get("policy_alignment") else None,
                "bid_rate_recommendation": bid_rate_recommendation if bid_rate_recommendation.get("optimal_rate") else None,
                "rfp_change_analysis": rfp_change_analysis if rfp_change_analysis.get("vs_last_year") else None,
                "proposal_enhancement": llm_raw.get("proposal_outline") and {
                    "title_strategy": llm_raw.get("bid_summary"),
                    "tech_differentiation": llm_raw.get("differentiation_strategy"),
                    "team_composition_advice": llm_raw.get("risk_factors"),
                    "pricing_strategy": llm_raw.get("budget_analysis"),
                },
                "llm_strategy_report": llm_raw.get("overall_recommendation") or llm_raw.get("proposal_outline"),
                "action_plan": llm_raw.get("action_items", []),
            },
            "metadata": result.get("metadata", {}),
        }

    except HTTPException:
        raise
    except asyncio.TimeoutError:
        logger.error("제안서 전략 분석 타임아웃: %s", request.bid_ntce_no)
        raise HTTPException(status_code=504, detail="분석 시간이 초과되었습니다. 다시 시도해주세요.")
    except Exception as e:
        logger.error("제안서 전략 분석 실패: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="서버 내부 오류가 발생했습니다")


@router.post("/analyses/chat", summary="AI 참여 전략 Q&A 대화")
async def analysis_chat(request: AnalysisChatRequest, db: DatabaseManager = Depends(get_db)):
    """
    제안서 고도화 전략 분석 결과에 대한 후속 Q&A 대화 API
    """
    try:
        config = load_config()

        # 공고 정보 로드
        bid = db.get_bid_by_no(request.bid_ntce_no)
        if not bid:
            raise HTTPException(
                status_code=404,
                detail=f"공고를 찾을 수 없습니다: {request.bid_ntce_no}"
            )

        # 사업자 정보 로드
        business = db.get_business(request.biz_id)
        if not business:
            raise HTTPException(
                status_code=404,
                detail=f"사업자를 찾을 수 없습니다: {request.biz_id}"
            )

        budget_str = f"{bid.budget:,}원" if bid.budget is not None else "정보 없음"
        revenue_str = f"{business.annual_revenue:,}원" if business.annual_revenue is not None else "정보 없음"

        # 챗봇을 위한 시스템 프롬프트 구성
        system_prompt = f"""당신은 입찰 전략 컨설턴트 AI입니다.
다음 공고와 사업자 정보를 바탕으로 사용자의 질문에 답하세요.

[입찰 공고 정보]
- 공고명: {bid.title}
- 발주기관: {bid.org_name}
- 추정가격: {budget_str}
- 마감일: {bid.bid_close_dt}
- 계약 방식: {bid.contract_method}
- 자격 요건: {bid.license_limit or "제한 없음"}

[사업자 정보 (귀사)]
- 회사명: {business.company_name}
- 보유 면허: {business.licenses}
- 과거 유사 실적: {business.past_projects}
- 연매출: {revenue_str}

사용자가 해당 공고의 제안서 작성, 수주 전략, 경쟁사 대응, 리스크 극복 방안 등에 대해 묻고 있습니다.
컨설턴트의 톤으로 전문적이고 구체적인 행동 전략(Action Plan) 위주로 답변을 제공하세요.
모든 답변은 한글로 작성하세요.
"""

        analyzer = LLMAnalyzer(config=config)
        
        history_str = ""
        if request.chat_history:
            history_str = "\n\n[이전 대화 기록]\n"
            for h in request.chat_history:
                role = "사용자" if h.get("role") == "user" else "AI"
                content = h.get("content", "")
                history_str += f"{role}: {content}\n"
        
        user_prompt = f"{history_str}\n\n사용자 질문: {request.message}\n\n이에 대한 답변을 생성해주세요."

        loop = asyncio.get_running_loop()
        with concurrent.futures.ThreadPoolExecutor() as pool:
            response = await loop.run_in_executor(
                pool,
                lambda: analyzer._call_api(system_prompt, user_prompt, max_tokens=1500, temperature=0.5)
            )

        return {"answer": response}

    except HTTPException:
        raise
    except Exception as e:
        logger.error("AI Q&A 대화 중 오류 발생: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="서버 내부 오류가 발생했습니다")


