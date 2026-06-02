"""
공고(입찰) API 라우트

/bids/* 엔드포인트: 목록 조회, 상세 조회, 수집, 유사 공고 비교(Diff)
"""

import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from src.config import load_config
from src.collectors.bid_collector import BidCollector

# 선택적 의존성: 설치되지 않았을 경우 None으로 대체
try:
    from src.analyzers.rfp_differ import RFPDiffer
except ImportError:
    RFPDiffer = None

from ._helpers import (
    get_db,
    _bid_to_api_dict,
    _bid_to_matcher_dict,
    _load_settings,
)
from ._models import BidCollectRequest

logger = logging.getLogger(__name__)

router = APIRouter(tags=["bids"])


# ──────────────────────────────────────────────
# 공고 API
# ──────────────────────────────────────────────


@router.get("/bids", summary="공고 목록 조회")
async def get_bids(
    keyword: Optional[str] = Query(None, description="공고명 검색 키워드"),
    org_name: Optional[str] = Query(None, description="발주기관명 검색"),
    limit: int = Query(50, ge=1, le=500, description="최대 반환 건수"),
    db=Depends(get_db),
):
    """
    DB에 저장된 입찰공고 목록을 검색합니다.

    keyword, org_name으로 필터링하고 limit으로 반환 건수를 제한합니다.
    """
    try:
        bids = db.search_bids(keyword=keyword, org_name=org_name, limit=limit)
        return [_bid_to_api_dict(b) for b in bids]
    except HTTPException:
        raise
    except Exception as e:
        logger.error("공고 목록 조회 실패: %s", e)
        raise HTTPException(status_code=500, detail="서버 내부 오류가 발생했습니다")


@router.get("/bids/{bid_ntce_no}", summary="공고 상세 조회")
async def get_bid_detail(bid_ntce_no: str, db=Depends(get_db)):
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
async def collect_bids(request: Optional[BidCollectRequest] = Body(None), db=Depends(get_db)):
    """
    나라장터 API를 호출하여 공고를 수집하고 DB에 저장합니다.

    start_date와 end_date를 지정하면 해당 기간의 공고를 수집하고,
    미지정 시 오늘자 공고를 수집합니다.
    body 없이 POST해도 오늘자 공고를 수집합니다.

    Returns:
        collected: 수집된 전체 공고 수
        saved: 새로 DB에 저장된 공고 수 (기존 중복 제외)
    """
    try:
        config = load_config()
        collector = BidCollector(config)
        user_settings = _load_settings()

        # 키워드, 날짜에 따라 수집 방법 선택 (to_thread로 블로킹 방지)
        if request and request.keyword:
            # 1) 사용자가 직접 키워드 지정
            bids = await asyncio.to_thread(collector.collect_bids_by_keyword, request.keyword, 30)
            used_keywords = [request.keyword]

        elif request and request.start_date and request.end_date:
            # 2) 날짜 범위 지정
            bids = await asyncio.to_thread(collector.collect_bids_by_date, request.start_date, request.end_date)
            used_keywords = []

        else:
            # 3) 기본: 저장된 관심 키워드로 수집
            saved_keywords = user_settings.get("keywords") or config.keywords or []
            exclude_keywords = user_settings.get("exclude_keywords") or []

            if saved_keywords:
                # 각 키워드로 나라장터 검색 → 결과 병합
                all_bids = []
                seen_nos = set()
                for kw in saved_keywords:
                    try:
                        kw_bids = await asyncio.to_thread(
                            collector.collect_bids_by_keyword, kw, 7
                        )
                        for b in kw_bids:
                            if b.bid_ntce_no not in seen_nos:
                                seen_nos.add(b.bid_ntce_no)
                                all_bids.append(b)
                        logger.info("키워드 '%s' → %d건 수집", kw, len(kw_bids))
                    except Exception as kw_err:
                        logger.warning("키워드 '%s' 수집 실패: %s", kw, kw_err)
                        continue

                # 제외 키워드 필터링
                if exclude_keywords:
                    before_count = len(all_bids)
                    all_bids = [
                        b for b in all_bids
                        if not any(ek in (b.title or '') for ek in exclude_keywords)
                    ]
                    logger.info("제외 키워드 필터링: %d → %d건", before_count, len(all_bids))

                bids = all_bids
                used_keywords = saved_keywords
            else:
                # 키워드 미설정 시 오늘 전체 공고 수집
                bids = await asyncio.to_thread(collector.collect_today_bids)
                used_keywords = []

        # DB에 저장
        saved_count = db.save_bids(bids) if bids else 0

        keyword_info = f" (키워드: {used_keywords})" if used_keywords else ""
        logger.info("공고 수집 완료: %d건 수집, %d건 저장%s", len(bids), saved_count, keyword_info)

        response = {
            "collected": len(bids),
            "saved": saved_count,
            "keywords_used": used_keywords,
        }

        # 디버그: 수집 실패 시 에러 힌트 제공
        if len(bids) == 0 and used_keywords:
            config = load_config()
            has_key = bool(config.data_go_kr_api_key)
            key_preview = config.data_go_kr_api_key[:8] + "..." if has_key else "MISSING"
            response["debug"] = {
                "api_key_set": has_key,
                "api_key_preview": key_preview,
                "hint": "API 키가 올바른지, 나라장터 API 서버 접근이 가능한지 확인하세요.",
            }
            # 단일 키워드 직접 테스트
            try:
                import requests as _req
                test_url = "https://apis.data.go.kr/1230000/ad/BidPublicInfoService/getBidPblancListInfoServc"
                test_resp = _req.get(test_url, params={
                    "ServiceKey": config.data_go_kr_api_key,
                    "numOfRows": "1", "pageNo": "1",
                    "inqryDiv": "1", "type": "json",
                    "bidNtceNm": used_keywords[0],
                    "inqryBgnDt": "202406010000",
                    "inqryEndDt": "202406302359",
                }, timeout=15)
                response["debug"]["test_status"] = test_resp.status_code
                response["debug"]["test_body_preview"] = test_resp.text[:300]
            except Exception as test_err:
                response["debug"]["test_error"] = str(test_err)

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
async def get_bid_diff(bid_ntce_no: str, db=Depends(get_db)):
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
