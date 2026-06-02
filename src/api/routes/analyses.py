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
from src.analyzers.biz_matcher import BizMatcher
from src.analyzers.llm_analyzer import LLMAnalyzer
from src.analyzers.strategy_engine import StrategyEngine

# 선택적 의존성: 설치되지 않았을 경우 None으로 대체
try:
    from src.analyzers.vector_store import VectorStore
except ImportError:
    VectorStore = None

from ._helpers import (
    get_db,
    _analysis_to_api_dict,
    _bid_to_matcher_dict,
    _biz_profile_to_matcher_dict,
    _load_settings,
)
from ._models import StrategyAnalysisRequest

logger = logging.getLogger(__name__)

router = APIRouter(tags=["analyses"])


# ──────────────────────────────────────────────
# 분석 API
# ──────────────────────────────────────────────


@router.post("/analyze", summary="참여 가능 공고 분석")
async def run_full_analysis(db=Depends(get_db)):
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
        logger.info("🏢 분석: 2단계 - 사업자 프로필 로드")
        biz_profiles = db.get_businesses()

        if not biz_profiles:
            return {
                "total_bids": len(bids),
                "participable": 0,
                "analyzed": 0,
                "results": [],
                "message": "등록된 사업자가 없습니다. 먼저 사업자를 등록해주세요.",
            }

        # ── 3단계: 사업자-공고 매칭 (참여 가능성 평가) ──
        logger.info("🎯 분석: 3단계 - 참여 가능 공고 필터링")
        biz_dicts = [_biz_profile_to_matcher_dict(bp) for bp in biz_profiles]
        bid_dicts = [_bid_to_matcher_dict(b) for b in bids]

        biz_matcher = BizMatcher()
        match_results = biz_matcher.match_all_bids(biz_dicts, bid_dicts)

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
                strategy = strategy_engine.generate_strategy(
                    bid=bid,
                    business_profile=business,
                    rfp_text=bid.get("rfp_text", ""),
                    past_awards=[],
                    news_articles=[],
                )

                # DB에 분석 결과 저장
                analysis = AnalysisResult(
                    bid_ntce_no=bid.get("bid_ntce_no", ""),
                    biz_id=business.get("biz_id", ""),
                    relevance_score=result.get("relevance_score", 0),
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
                    "error": str(e),
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
    db=Depends(get_db),
):
    """
    분석 결과 목록을 조회합니다.

    bid_ntce_no 또는 biz_id로 필터링할 수 있습니다.
    필터가 없으면 최근 분석 결과 전체를 반환합니다.
    """
    try:
        if bid_ntce_no:
            results = db.get_analyses_by_bid(bid_ntce_no)
        elif biz_id:
            results = db.get_analyses_by_biz(biz_id)
        else:
            # 전체 최근 결과 조회 (커스텀 쿼리)
            conn = db.get_connection()
            cursor = conn.execute(
                """
                SELECT * FROM analysis_results
                ORDER BY analyzed_at DESC
                LIMIT 100
                """
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

        # 공고 정보 JOIN
        enriched = []
        for r in unique:
            d = _analysis_to_api_dict(r)
            try:
                bid = db.get_bid_by_no(r.bid_ntce_no)
                if bid:
                    d["bid_title"] = bid.title or r.bid_ntce_no
                    d["org_name"] = bid.org_name or ""
                    d["budget"] = bid.budget or 0
                    d["bid_close_dt"] = bid.bid_close_dt or ""
                else:
                    d["bid_title"] = r.bid_ntce_no
                    d["org_name"] = ""
                    d["budget"] = 0
            except Exception:
                d["bid_title"] = r.bid_ntce_no
                d["org_name"] = ""
                d["budget"] = 0
            # 사업자명 조회
            if r.biz_id:
                try:
                    biz = db.get_business(r.biz_id)
                    if biz:
                        d["company_name"] = biz.company_name
                except Exception:
                    pass
            enriched.append(d)

        return enriched
    except HTTPException:
        raise
    except Exception as e:
        logger.error("분석 결과 목록 조회 실패: %s", e)
        raise HTTPException(status_code=500, detail="서버 내부 오류가 발생했습니다")


@router.get("/analyses/{analysis_id}", summary="분석 결과 상세 조회")
async def get_analysis_detail(analysis_id: int, db=Depends(get_db)):
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


@router.delete("/analyses/{analysis_id}", summary="분석 결과 삭제")
async def delete_analysis(analysis_id: int, db=Depends(get_db)):
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
async def delete_all_analyses(db=Depends(get_db)):
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
async def analyze_strategy(request: StrategyAnalysisRequest, db=Depends(get_db)):
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
        biz_profiles = db.get_businesses()

        best_match = {}
        business = {}
        match_score = 0.0
        match_results = []

        if biz_profiles:
            # 최적 사업자 매칭
            biz_dicts = [_biz_profile_to_matcher_dict(bp) for bp in biz_profiles]
            biz_matcher = BizMatcher()
            match_results = biz_matcher.match_all_bids(biz_dicts, [bid_dict])
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
                vector_store.add_context(
                    bid_ntce_no=request.bid_ntce_no,
                    text=bid.rfp_text or bid_title,
                    metadata={"strategy": strategy.get("bid_summary", "")},
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
