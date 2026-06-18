"""
지자체 정책 및 뉴스 분석 API 라우터

전국 지자체의 고시공고 및 관련 뉴스 데이터를 조회하고,
수집 시뮬레이션 및 자연어 처리(NLP) 분석 엔진을 트리거합니다.
인증 없이 누구나 조회 및 수집/분석을 실행할 수 있습니다.
"""

import json
import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks, status

from src.models.database import DatabaseManager
from ._helpers import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/policies", tags=["policies"])


# ──────────────────────────────────────────────
# 내부 헬퍼 함수
# ──────────────────────────────────────────────

def _run_collect_task():
    """백그라운드 수집 태스크"""
    try:
        import sys
        from pathlib import Path
        project_root = Path(__file__).resolve().parent.parent.parent.parent
        if str(project_root) not in sys.path:
            sys.path.insert(0, str(project_root))

        from scripts.collect_policies import run_collector_pipeline
        logger.info("🎬 백그라운드 지자체 정책 수집 파이프라인 시작...")
        run_collector_pipeline()
        logger.info("🏁 백그라운드 지자체 정책 수집 파이프라인 완료!")
    except Exception as e:
        logger.error("백그라운드 지자체 정책 수집 실패: %s", e)


def _run_nlp_task():
    """백그라운드 NLP 분석 태스크"""
    try:
        import sys
        from pathlib import Path
        project_root = Path(__file__).resolve().parent.parent.parent.parent
        if str(project_root) not in sys.path:
            sys.path.insert(0, str(project_root))

        from scripts.run_nlp import NLPEngine
        logger.info("🎬 백그라운드 지자체 정책 NLP 분석 엔진 시작...")
        engine = NLPEngine()
        results = engine.run_analysis()

        # 분석 결과를 통합 DB에 업데이트
        from src.models.database import DatabaseManager as _DB
        db = _DB()
        db.connect()
        updated_count = 0
        try:
            for r in results:
                success = db.update_municipal_policy_nlp(
                    policy_id=r["id"],
                    keywords=r["keywords"],
                    ai_summary=r["ai_summary"],
                    relevance_score=r["relevance_score"]
                )
                if success:
                    updated_count += 1
        finally:
            db.close()

        logger.info("🏁 NLP 분석 완료! 업데이트: %d/%d건", updated_count, len(results))
    except Exception as e:
        logger.error("백그라운드 지자체 정책 NLP 분석 실패: %s", e)


# ──────────────────────────────────────────────
# GET 엔드포인트
# ──────────────────────────────────────────────

@router.get("/stats", summary="지자체별 정책 분석 통계 조회")
async def get_policy_stats(db: DatabaseManager = Depends(get_db)):
    """전국 지자체별로 수집된 정책 건수, 총 예산 규모, 평균 연관성 지수 통계를 조회합니다."""
    try:
        stats = db.get_municipal_policies_stats()

        total_count = sum(s.get("count", 0) for s in stats)
        total_budget = sum(s.get("total_budget") or 0 for s in stats)
        avg_relevance = (
            sum(s.get("avg_relevance") or 0 for s in stats) / len(stats)
            if stats else 0
        )

        return {
            "success": True,
            "summary": {
                "total_count": total_count,
                "total_budget": total_budget,
                "avg_relevance": round(avg_relevance, 1),
                "region_count": len(stats),
            },
            "stats": stats,
        }
    except Exception as e:
        logger.error("지자체 정책 통계 조회 실패: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="지자체 정책 통계를 가져오는 도중 오류가 발생했습니다.",
        )


@router.get("/categories", summary="정책 카테고리 목록 조회")
async def get_policy_categories(db: DatabaseManager = Depends(get_db)):
    """현재 DB에 존재하는 고유 카테고리 목록을 반환합니다."""
    try:
        conn = db._ensure_connection()
        cursor = conn.execute(
            "SELECT DISTINCT category FROM municipal_policies WHERE category IS NOT NULL ORDER BY category"
        )
        categories = [row[0] for row in cursor.fetchall()]
        if not categories:
            categories = ["ICT/교통", "문화/공간정보", "소상공인/경제", "창업/R&D"]
        return {"success": True, "categories": categories}
    except Exception as e:
        logger.error("카테고리 목록 조회 실패: %s", e)
        return {
            "success": True,
            "categories": ["ICT/교통", "문화/공간정보", "소상공인/경제", "창업/R&D"],
        }


@router.get("", summary="지자체 정책 목록 조회")
async def get_policies(
    region: Optional[str] = Query(None, description="지자체 지역 명칭"),
    category: Optional[str] = Query(None, description="정책 카테고리"),
    search: Optional[str] = Query(None, description="제목 또는 내용 검색어"),
    page: int = Query(1, ge=1, description="페이지 번호"),
    limit: int = Query(12, ge=1, le=100, description="한 페이지당 개수"),
    db: DatabaseManager = Depends(get_db),
):
    """수집 및 분석 완료된 전국 지자체의 정책 목록을 필터링 조건에 맞추어 조회합니다."""
    offset = (page - 1) * limit
    try:
        policies = db.get_municipal_policies(
            region=region,
            category=category,
            search=search,
            limit=limit,
            offset=offset,
        )

        # 전체 개수 집계 (페이지네이션용)
        conn = db._ensure_connection()
        count_query = "SELECT COUNT(*) FROM municipal_policies WHERE 1=1"
        count_params: list = []
        if region:
            count_query += " AND region = ?"
            count_params.append(region)
        if category:
            count_query += " AND category = ?"
            count_params.append(category)
        if search:
            count_query += " AND (title LIKE ? OR content LIKE ?)"
            count_params.extend([f"%{search}%", f"%{search}%"])
        total_count = conn.execute(count_query, count_params).fetchone()[0]

        return {
            "success": True,
            "page": page,
            "limit": limit,
            "count": len(policies),
            "total_count": total_count,
            "has_next": (offset + len(policies)) < total_count,
            "policies": policies,
        }
    except Exception as e:
        logger.error("지자체 정책 목록 조회 실패: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="지자체 정책 목록을 가져오는 도중 오류가 발생했습니다.",
        )


@router.get("/{policy_id}", summary="단일 정책 상세 조회")
async def get_policy_detail(
    policy_id: int,
    db: DatabaseManager = Depends(get_db),
):
    """특정 정책의 상세 정보를 조회합니다."""
    try:
        conn = db._ensure_connection()
        cursor = conn.execute(
            "SELECT * FROM municipal_policies WHERE id = ?", (policy_id,)
        )
        row = cursor.fetchone()
        if not row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"ID {policy_id}에 해당하는 정책을 찾을 수 없습니다.",
            )
        item = dict(row)
        try:
            item["keywords"] = json.loads(item["keywords"]) if item.get("keywords") else []
        except Exception:
            item["keywords"] = []
        try:
            item["metadata"] = json.loads(item["metadata"]) if item.get("metadata") else {}
        except Exception:
            item["metadata"] = {}
        return {"success": True, "policy": item}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("정책 상세 조회 실패 [ID: %s]: %s", policy_id, e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="정책 상세 정보를 가져오는 도중 오류가 발생했습니다.",
        )


# ──────────────────────────────────────────────
# POST 엔드포인트 (인증 불필요)
# ──────────────────────────────────────────────

@router.post("/collect", summary="지자체 정책 데이터 실시간 수집")
async def collect_policies(
    background_tasks: BackgroundTasks,
    db: DatabaseManager = Depends(get_db),
):
    """
    전국 지자체의 최신 정책 및 고시공고 데이터를 실시간 수집합니다.
    백그라운드에서 실행되며 인증이 필요하지 않습니다.
    """
    try:
        background_tasks.add_task(_run_collect_task)
        return {
            "success": True,
            "message": "지자체 정책 데이터 수집 파이프라인이 백그라운드에서 즉시 시작되었습니다.",
        }
    except Exception as e:
        logger.error("지자체 정책 수집 실패: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"수집 파이프라인 트리거 중 오류가 발생했습니다: {str(e)}",
        )


@router.post("/analyze", summary="지자체 정책 데이터 AI NLP 분석")
async def analyze_policies(
    background_tasks: BackgroundTasks,
    db: DatabaseManager = Depends(get_db),
):
    """
    수집된 지자체 정책 텍스트에 대해 TF-IDF 기반 핵심 키워드 추출 및
    AI 3줄 요약, 추천도 지수 계산을 실행합니다.
    인증이 필요하지 않습니다.
    """
    try:
        background_tasks.add_task(_run_nlp_task)
        return {
            "success": True,
            "message": "AI NLP 분석 파이프라인이 백그라운드에서 시작되었습니다. 잠시 후 결과가 갱신됩니다.",
        }
    except Exception as e:
        logger.error("지자체 정책 NLP 분석 실패: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"NLP 분석 파이프라인 트리거 중 오류가 발생했습니다: {str(e)}",
        )
