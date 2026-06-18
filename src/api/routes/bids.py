"""
공고(입찰) API 라우트

/bids/* 엔드포인트: 목록 조회, 상세 조회, 수집, 유사 공고 비교(Diff)
"""

import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from src.config import load_config
from src.collectors.universal_collector import UniversalBidCollector

# 선택적 의존성: 설치되지 않았을 경우 None으로 대체
try:
    from src.analyzers.rfp_differ import RFPDiffer
except ImportError:
    RFPDiffer = None

from src.models.database import DatabaseManager
from ._helpers import (
    get_db,
    _bid_to_api_dict,
    _bid_to_matcher_dict,
    _load_settings,
)
from ._models import BidCollectRequest

logger = logging.getLogger(__name__)

router = APIRouter(tags=["bids"])


@router.get("/debug/collect-test", summary="수집 파이프라인 진단")
async def debug_collect():
    """수집 과정을 단계별로 실행하고 각 단계의 결과를 반환합니다. DEV_MODE에서만 사용 가능."""
    import os
    if not os.getenv("DEV_MODE", "").lower() in ("true", "1", "yes"):
        raise HTTPException(status_code=404, detail="Not found")
    import requests as _req
    from datetime import datetime, timedelta
    from src.config import load_config

    config = load_config()
    result = {"steps": []}

    # Step 1: API 키
    result["steps"].append({
        "step": "1_api_key",
        "has_key": bool(config.data_go_kr_api_key),
        "key_len": len(config.data_go_kr_api_key) if config.data_go_kr_api_key else 0,
    })

    # Step 2: 날짜 범위
    end_dt = datetime.now()
    start_dt = end_dt - timedelta(days=7)
    start_date = start_dt.strftime("%Y%m%d") + "0000"
    end_date = end_dt.strftime("%Y%m%d") + "2359"
    result["steps"].append({
        "step": "2_dates",
        "now": str(end_dt),
        "start": start_date,
        "end": end_date,
    })

    # Step 3: 직접 API 호출
    api_url = "https://apis.data.go.kr/1230000/ad/BidPublicInfoService/getBidPblancListInfoServc"
    params = {
        "ServiceKey": config.data_go_kr_api_key,
        "numOfRows": "2", "pageNo": "1",
        "inqryDiv": "1", "type": "json",
        "bidNtceNm": "마케팅",
        "inqryBgnDt": start_date,
        "inqryEndDt": end_date,
    }
    try:
        resp = _req.get(api_url, params=params, timeout=15)
        body_text = resp.text[:500]
        result["steps"].append({
            "step": "3_raw_api",
            "http_status": resp.status_code,
            "body_preview": body_text,
        })

        data = resp.json()
        hdr = data.get("response", {}).get("header", {})
        bdy = data.get("response", {}).get("body", {})
        items = bdy.get("items", [])
        result["steps"].append({
            "step": "4_parsed",
            "resultCode": hdr.get("resultCode"),
            "totalCount": bdy.get("totalCount"),
            "items_type": type(items).__name__,
            "items_len": len(items) if isinstance(items, list) else "dict",
        })

        # Step 5: BidAnnouncement 파싱
        from src.models.schemas import BidAnnouncement
        test_list = items if isinstance(items, list) else items.get("item", [])
        if isinstance(test_list, dict):
            test_list = [test_list]
        parse_ok = []
        parse_fail = []
        for item in test_list[:2]:
            try:
                bid = BidAnnouncement.from_dict(item)
                parse_ok.append(bid.bid_ntce_no)
            except Exception as e:
                parse_fail.append(str(e))
        result["steps"].append({
            "step": "5_parse",
            "ok": parse_ok,
            "fail": parse_fail,
        })
    except Exception as e:
        result["steps"].append({"step": "3_error", "error": str(e)})

    # Step 6: Collector 실행
    try:
        collector = BidCollector(config)
        bids = collector.collect_bids_by_keyword("마케팅", 7)
        result["steps"].append({
            "step": "6_collector",
            "count": len(bids),
            "first": bids[0].bid_ntce_no if bids else None,
        })
    except Exception as e:
        result["steps"].append({"step": "6_error", "error": str(e), "type": type(e).__name__})

    return result


# ──────────────────────────────────────────────
# 공고 API
# ──────────────────────────────────────────────


@router.get("/bids/cache/stats", summary="공고 캐시 현황 조회")
async def get_bids_cache_stats(db: DatabaseManager = Depends(get_db)):
    """
    공유 공고 DB 캐시 현황을 반환합니다.
    총 공고 수, 오늘 수집 수, 마지막 수집 시각, 카테고리별 통계
    """
    try:
        conn = db._ensure_connection()
        ph = "%s" if db.is_postgres else "?"
        from datetime import datetime
        today = datetime.now().strftime("%Y-%m-%d")

        total = conn.execute("SELECT COUNT(*) FROM bid_announcements").fetchone()[0]
        today_count = conn.execute(
            f"SELECT COUNT(*) FROM bid_announcements WHERE collected_at >= {ph}", (today,)
        ).fetchone()[0]

        last_row = conn.execute(
            "SELECT MAX(collected_at) FROM bid_announcements"
        ).fetchone()
        last_collected = last_row[0] if last_row else None

        # 카테고리별 통계
        try:
            cat_rows = conn.execute(
                "SELECT category, COUNT(*) FROM bid_announcements GROUP BY category ORDER BY COUNT(*) DESC LIMIT 10"
            ).fetchall()
            by_category = [{"category": r[0] or "미분류", "count": r[1]} for r in cat_rows]
        except Exception:
            by_category = []

        # 최근 7일 일별 수집 현황
        try:
            if db.is_postgres:
                daily_rows = conn.execute(
                    "SELECT DATE(collected_at::timestamp) as day, COUNT(*) FROM bid_announcements "
                    "WHERE collected_at >= NOW() - INTERVAL '7 days' GROUP BY day ORDER BY day"
                ).fetchall()
            else:
                daily_rows = conn.execute(
                    "SELECT DATE(collected_at) as day, COUNT(*) FROM bid_announcements "
                    "WHERE collected_at >= DATE('now', '-7 days') GROUP BY day ORDER BY day"
                ).fetchall()
            daily = [{"date": str(r[0]), "count": r[1]} for r in daily_rows]
        except Exception:
            daily = []

        return {
            "total": total,
            "today": today_count,
            "last_collected": last_collected,
            "by_category": by_category,
            "daily_7days": daily,
            "cache_note": "모든 사용자가 공유하는 공고 캐시 DB입니다. 새 공고 검색 시 자동으로 여기에 저장됩니다."
        }
    except Exception as e:
        logger.error("캐시 현황 조회 실패: %s", e)
        raise HTTPException(status_code=500, detail="캐시 현황 조회 실패")


@router.get("/bids", summary="공고 목록 조회 (DB 캐시 우선)")
async def get_bids(
    keyword: Optional[str] = Query(None, description="공고명 검색 키워드"),
    org_name: Optional[str] = Query(None, description="발주기관명 검색"),
    limit: int = Query(50, ge=1, le=500, description="최대 반환 건수"),
    smart_fetch: bool = Query(False, description="True면 DB 결과 부족 시 API 수집 후 저장"),
    db: DatabaseManager = Depends(get_db),
):
    """
    DB 캐시에서 공고를 조회합니다.

    - 기본: DB에서만 조회 (빠름)
    - smart_fetch=true: DB 결과가 부족하면 API 수집 후 DB에 저장하고 반환
    """
    try:
        bids = db.search_bids(keyword=keyword, org_name=org_name, limit=limit)

        # 스마트 페치: DB에 결과가 없거나 부족하면 API 수집 후 저장
        if smart_fetch and keyword and len(bids) < 5:
            logger.info("DB 캐시 부족(%d건) → API 수집 시작 (키워드: %s)", len(bids), keyword)
            try:
                config = load_config()
                collector = UniversalBidCollector(config)
                from datetime import datetime, timedelta
                from zoneinfo import ZoneInfo
                kst_now = datetime.now(tz=ZoneInfo("Asia/Seoul"))
                start_dt = (kst_now - timedelta(days=30)).strftime("%Y%m%d")
                end_dt = kst_now.strftime("%Y%m%d")
                raw_bids = await asyncio.to_thread(
                    collector.collect_all_sources, start_dt, end_dt, [], keyword
                )
                new_bids = [b for b in raw_bids if keyword.lower() in (b.title or '').lower()]
                if new_bids:
                    saved = db.save_bids(new_bids)
                    logger.info("스마트 페치: %d건 수집 → %d건 신규 저장 (키워드: %s)", len(new_bids), saved, keyword)
                    # 저장 후 다시 DB에서 조회
                    bids = db.search_bids(keyword=keyword, org_name=org_name, limit=limit)
            except Exception as fetch_err:
                logger.warning("스마트 페치 수집 실패 (DB 결과 반환): %s", fetch_err)

        return [_bid_to_api_dict(b) for b in bids]
    except HTTPException:
        raise
    except Exception as e:
        logger.error("공고 목록 조회 실패: %s", e)
        raise HTTPException(status_code=500, detail="서버 내부 오류가 발생했습니다")


@router.get("/bids/{bid_ntce_no}", summary="공고 상세 조회")
async def get_bid_detail(bid_ntce_no: str, db: DatabaseManager = Depends(get_db)):
    """공고번호로 입찰공고 상세 정보를 조회합니다."""
    try:
        bid = db.get_bid_by_no(bid_ntce_no)
        if not bid:
            raise HTTPException(
                status_code=404,
                detail=f"공고를 찾을 수 없습니다: {bid_ntce_no}",
            )
        return _bid_to_api_dict(bid)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("공고 상세 조회 실패: %s", e)
        raise HTTPException(status_code=500, detail="서버 내부 오류가 발생했습니다")


@router.post("/bids/collect", summary="관심 키워드 기반 공고 수집")
async def collect_bids(request: Optional[BidCollectRequest] = Body(None), db: DatabaseManager = Depends(get_db)):
    """
    국내외 조달/용역 API 및 소스 채널을 호출하여 공고를 수집하고 DB에 저장합니다.

    start_date와 end_date를 지정하면 해당 기간의 공고를 수집하고,
    미지정 시 오늘자 공고를 수집합니다.
    platforms에 수집할 플랫폼 리스트를 실어 보내면 선별 수집합니다.

    Returns:
        collected: 수집된 전체 공고 수
        saved: 새로 DB에 저장된 공고 수 (기존 중복 제외)
    """
    try:
        kw_errors = []
        config = load_config()
        collector = UniversalBidCollector(config)
        user_settings = _load_settings()
        
        platforms = request.platforms if request else []

        # 키워드, 날짜에 따라 수집 방법 선택 (to_thread로 블로킹 방지)
        if request and request.keyword:
            # 1) 사용자가 직접 키워드 지정 (최근 30일 수집 후 파이썬 상에서 키워드 필터링)
            from datetime import datetime, timedelta
            from zoneinfo import ZoneInfo
            kst_now = datetime.now(tz=ZoneInfo("Asia/Seoul"))
            start_dt = (kst_now - timedelta(days=30)).strftime("%Y%m%d")
            end_dt = kst_now.strftime("%Y%m%d")
            
            raw_bids = await asyncio.to_thread(collector.collect_all_sources, start_dt, end_dt, platforms, request.keyword)
            bids = [b for b in raw_bids if request.keyword.lower() in (b.title or '').lower()]
            used_keywords = [request.keyword]

        elif request and request.start_date and request.end_date:
            # 2) 날짜 범위 지정
            bids = await asyncio.to_thread(collector.collect_all_sources, request.start_date, request.end_date, platforms)
            used_keywords = []

        else:
            # 3) 기본: 저장된 관심 키워드 및 지정 플랫폼으로 수집
            saved_keywords = user_settings.get("keywords") or config.keywords or []
            exclude_keywords = user_settings.get("exclude_keywords") or []

            if saved_keywords:
                # 지정 키워드로 통합 수집 및 필터링
                raw_bids = await asyncio.to_thread(collector.collect_all_sources, "", "", platforms)
                filtered_bids = []
                seen_nos = set()
                
                for b in raw_bids:
                    # 저장된 관심 키워드가 하나라도 제목에 포함되는지 확인
                    match_kw = any(kw.lower() in (b.title or '').lower() for kw in saved_keywords)
                    # 제외 키워드가 포함 안 되는지 확인
                    match_exclude = any(ek.lower() in (b.title or '').lower() for ek in exclude_keywords) if exclude_keywords else False
                    
                    if match_kw and not match_exclude and b.bid_ntce_no not in seen_nos:
                        seen_nos.add(b.bid_ntce_no)
                        filtered_bids.append(b)
                
                bids = filtered_bids
                used_keywords = saved_keywords
            else:
                # 키워드 미설정 시 지정 플랫폼의 오늘 전체 공고 수집
                bids = await asyncio.to_thread(collector.collect_all_sources, "", "", platforms)
                used_keywords = []

        # DB에 저장
        saved_count = db.save_bids(bids) if bids else 0

        keyword_info = f" (키워드: {used_keywords})" if used_keywords else ""
        logger.info("통합 공고 수집 완료: %d건 수집, %d건 저장%s (플랫폼: %s)", 
                    len(bids), saved_count, keyword_info, platforms)

        response = {
            "collected": len(bids),
            "saved": saved_count,
            "keywords_used": used_keywords,
            "platforms_used": platforms,
        }

        # 수집 실패 시 힌트 제공
        if len(bids) == 0 and used_keywords:
            response["hint"] = "API 키가 올바른지, 혹은 수집 채널 접근이 가능한지 확인하세요."

        return response
    except HTTPException:
        raise
    except Exception as e:
        logger.error("공고 수집 실패: %s", e)
        raise HTTPException(status_code=500, detail="서버 내부 오류가 발생했습니다")


# ──────────────────────────────────────────────
# 유사 공고 비교(Diff) API
# ──────────────────────────────────────────────


@router.get("/bids/{bid_ntce_no}/diff", summary="유사 과거 공고 비교")
async def get_bid_diff(bid_ntce_no: str, db: DatabaseManager = Depends(get_db)):
    """
    현재 공고와 가장 유사한 과거 공고를 찾아 변경사항(diff)을 반환합니다.

    RFPDiffer 모듈이 설치되어 있어야 작동합니다.
    유사 공고가 없을 경우 diff=null과 안내 메시지를 반환합니다.

    Args:
        bid_ntce_no: 비교 대상 공고번호

    Returns:
        current_bid, past_bid, diff, key_changes, similarity 정보
    """
    # RFPDiffer 모듈 존재 여부 확인
    if RFPDiffer is None:
        raise HTTPException(
            status_code=501,
            detail="RFPDiffer 모듈이 설치되지 않았습니다.",
        )

    try:
        # ── 현재 공고 로드 ──
        bid = db.get_bid_by_no(bid_ntce_no)
        if not bid:
            raise HTTPException(
                status_code=404,
                detail=f"공고를 찾을 수 없습니다: {bid_ntce_no}",
            )

        current_bid_dict = _bid_to_api_dict(bid)

        # ── 유사 과거 공고 검색 ──
        try:
            differ = RFPDiffer()
            past_bid_result = differ.find_similar_past_bid(db, current_bid_dict)
        except Exception as e:
            logger.warning("유사 공고 검색 실패: %s", e)
            return {
                "current_bid": current_bid_dict,
                "past_bid": None,
                "diff": None,
                "key_changes": [],
                "similarity": 0.0,
                "message": "유사 공고 검색 중 오류가 발생했습니다.",
            }

        # 유사 공고가 없는 경우
        if not past_bid_result or not past_bid_result.get("past_bid"):
            return {
                "current_bid": current_bid_dict,
                "past_bid": None,
                "diff": None,
                "key_changes": [],
                "similarity": 0.0,
                "message": "유사 공고 없음",
            }

        # ── Diff 계산 ──
        past_bid = past_bid_result["past_bid"]
        past_bid_dict = _bid_to_api_dict(past_bid) if hasattr(past_bid, "bid_ntce_no") else past_bid

        # 제목·설명 기반 diff 생성
        current_text = f"{bid.title or ''}\n{bid.rfp_text or ''}"
        past_title = past_bid.title if hasattr(past_bid, "title") else past_bid.get("title", "")
        past_rfp = past_bid.rfp_text if hasattr(past_bid, "rfp_text") else past_bid.get("rfp_text", "")
        past_text = f"{past_title or ''}\n{past_rfp or ''}"

        try:
            diff_result = differ.compute_diff(past_text, current_text)
        except Exception as e:
            logger.warning("Diff 계산 실패: %s", e)
            diff_result = {"diff": "Diff 계산 실패", "key_changes": []}

        return {
            "current_bid": current_bid_dict,
            "past_bid": past_bid_dict,
            "diff": diff_result.get("diff"),
            "key_changes": diff_result.get("key_changes", []),
            "similarity": past_bid_result.get("similarity", 0.0),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("유사 공고 비교 실패: %s", e)
        raise HTTPException(status_code=500, detail="서버 내부 오류가 발생했습니다")
