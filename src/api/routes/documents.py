"""
문서/뉴스 API 라우트

/news/* 엔드포인트: 기관별 뉴스 조회
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from src.config import load_config
from src.collectors.news_collector import NewsCollector

from ._helpers import get_db

logger = logging.getLogger(__name__)

router = APIRouter(tags=["documents"])


def _article_to_dict(a) -> dict:
    """NewsArticle 객체를 API 응답용 딕셔너리로 변환합니다."""
    return {
        "id": a.id,
        "title": a.title,
        "description": a.description,
        "link": a.link,
        "pub_date": a.pub_date,
        "search_query": a.search_query,
        "collected_at": a.collected_at.strftime("%Y-%m-%d %H:%M:%S") if a.collected_at else None,
    }


# ──────────────────────────────────────────────
# 기관 뉴스 조회 API
# ──────────────────────────────────────────────


@router.get("/news/{org_name}", summary="기관별 뉴스 조회")
async def get_org_news(
    org_name: str,
    limit: int = Query(20, ge=1, le=100, description="최대 반환 건수"),
    db=Depends(get_db),
):
    """
    특정 기관의 뉴스 기사를 조회합니다.

    우선 DB 캐시에서 조회하고, 결과가 없으면 네이버 API를 통해
    실시간 수집 후 DB에 저장합니다.

    Args:
        org_name: 조회할 기관명
        limit: 최대 반환 건수 (기본 20)

    Returns:
        뉴스 기사 리스트 (제목, 요약, 링크, 발행일 등)
    """
    try:
        # ── 1단계: DB 캐시 조회 ──
        cached_articles = db.get_news_by_query(org_name, limit=limit)

        if cached_articles:
            logger.info("DB 캐시에서 뉴스 %d건 반환: '%s'", len(cached_articles), org_name)
            return {
                "articles": [_article_to_dict(a) for a in cached_articles],
            }

        # ── 2단계: 네이버 API로 실시간 수집 ──
        config = load_config()
        if not (config.naver_client_id and config.naver_client_secret):
            return {
                "articles": [],
                "message": "네이버 API 키가 설정되지 않아 뉴스를 수집할 수 없습니다.",
            }

        news_collector = NewsCollector(config)
        articles = news_collector.search_news(org_name, display=limit, sort="date")

        # ── 3단계: DB에 저장 ──
        if articles:
            try:
                db.save_news(articles)
                logger.info("뉴스 %d건 수집 및 저장 완료: '%s'", len(articles), org_name)
            except Exception as e:
                logger.warning("뉴스 DB 저장 실패: %s", e)

        # ── 4단계: 결과 반환 ──
        return {
            "articles": [_article_to_dict(a) for a in articles],
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("기관 뉴스 조회 실패 ('%s'): %s", org_name, e)
        raise HTTPException(status_code=500, detail="서버 내부 오류가 발생했습니다")
