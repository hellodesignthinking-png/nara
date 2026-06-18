"""
관심공고 API 라우터

사용자별 관심공고(user_favorites)의 추가, 조회, 수정, 삭제 및
로그인 시 로컬스토리지 데이터를 서버로 동기화(sync)하는 API를 제공합니다.
"""

import logging
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, status, Request
from pydantic import BaseModel

from src.models.database import DatabaseManager
from ._helpers import get_db, get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/favorites", tags=["favorites"])

# ──────────────────────────────────────────────
# Pydantic 모델
# ──────────────────────────────────────────────

class FavoriteAddRequest(BaseModel):
    bid_ntce_no: str
    status: Optional[str] = "reviewing"
    memo: Optional[str] = ""
    partners: Optional[list] = []
    checklist: Optional[list] = []
    title: Optional[str] = None
    org_name: Optional[str] = None
    budget: Optional[int] = None
    bid_close_dt: Optional[str] = None

class FavoriteUpdateRequest(BaseModel):
    status: Optional[str] = None
    memo: Optional[str] = None
    partners: Optional[list] = None
    checklist: Optional[list] = None
    # AI 분석 결과 자동 저장 필드
    analysis_done: Optional[bool] = None
    analysis_summary: Optional[str] = None
    title: Optional[str] = None
    org_name: Optional[str] = None

class FavoriteSyncRequest(BaseModel):
    favorites: List[FavoriteAddRequest]

# ──────────────────────────────────────────────
# 엔드포인트 구현
# ──────────────────────────────────────────────

@router.get("", summary="관심공고 목록 조회")
async def get_favorites(
    request: Request,
    username: str = Depends(get_current_user),
    db: DatabaseManager = Depends(get_db)
):
    """
    현재 로그인한 사용자의 전체 관심공고 목록을 가져옵니다.
    활성 회사 정보가 제공되면 실시간 AI 가중치 기반 매칭 점수를 추가하여 반환합니다.
    """
    try:
        favs = db.get_favorites(username)
        active_biz_id = request.headers.get("X-Active-Company")
        
        if active_biz_id and favs:
            from src.analyzers.biz_matcher import BizMatcher
            from ._helpers import _biz_profile_to_matcher_dict, _bid_to_matcher_dict
            
            biz_profile = db.get_business(active_biz_id)
            if biz_profile:
                matcher = BizMatcher()
                ai_settings = db.get_user_ai_settings(username)
                biz_dict = _biz_profile_to_matcher_dict(biz_profile)
                
                for f in favs:
                    full_bid = db.get_bid_by_no(f["bid_ntce_no"])
                    if full_bid:
                        bid_dict = _bid_to_matcher_dict(full_bid)
                        score_res = matcher.calculate_match_score(biz_dict, bid_dict, ai_settings)
                        f["match_score"] = score_res.get("total_score", 0.0)
                        f["recommendation"] = score_res.get("recommendation", "참여 검토")
                    else:
                        f["match_score"] = 0.0
                        f["recommendation"] = "정보 없음"
        return favs
    except Exception as e:
        logger.error("관심공고 목록 조회 실패: %s", e)
        raise HTTPException(status_code=500, detail="관심공고를 가져오는 도중 서버 오류가 발생했습니다.")

@router.post("", summary="관심공고 추가", status_code=201)
async def add_favorite(request: FavoriteAddRequest, username: str = Depends(get_current_user), db: DatabaseManager = Depends(get_db)):
    """
    현재 로그인한 사용자의 관심공고로 등록합니다.
    """
    bid_no = request.bid_ntce_no.strip()
    if not bid_no:
        raise HTTPException(status_code=400, detail="입찰공고번호(bid_ntce_no)는 필수입니다.")
        
    try:
        db.add_favorite(
            username=username,
            bid_ntce_no=request.bid_ntce_no,
            status=request.status,
            memo=request.memo,
            partners=request.partners,
            checklist=request.checklist,
            title=request.title,
            org_name=request.org_name,
            budget=request.budget,
            bid_close_dt=request.bid_close_dt,
        )
        # title/org_name 이 있으면 즉시 update_favorite 로 저장
        if request.title or request.org_name:
            db.update_favorite(
                username=username,
                bid_ntce_no=bid_no,
                title=request.title,
                org_name=request.org_name,
            )
        return {"message": "관심공고에 등록되었습니다.", "bid_ntce_no": bid_no}
    except Exception as e:
        logger.error("관심공고 추가 실패: %s", e)
        raise HTTPException(status_code=500, detail="관심공고를 추가하는 도중 서버 오류가 발생했습니다.")

@router.put("/{bid_ntce_no}", summary="관심공고 내용 수정")
async def update_favorite(
    bid_ntce_no: str,
    request: FavoriteUpdateRequest,
    username: str = Depends(get_current_user),
    db: DatabaseManager = Depends(get_db)
):
    """
    관심공고의 진행 상태, 메모, 협업 파트너, 체크리스트 항목을 실시간 업데이트합니다.
    관심공고가 없는 경우 자동으로 추가(UPSERT)합니다.
    """
    try:
        # 업데이트할 필드만 전달 (없는 필드는 None 유지)
        success = db.update_favorite(
            username=username,
            bid_ntce_no=bid_ntce_no,
            status=request.status,
            memo=request.memo,
            partners=request.partners,
            checklist=request.checklist,
            analysis_done=request.analysis_done,
            analysis_summary=request.analysis_summary,
        )
        # 성공 여부와 관계없이 200 반환 (UPSERT 완료)
        return {"message": "관심공고가 성공적으로 업데이트되었습니다.", "upserted": not success}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("관심공고 업데이트 실패: %s", e)
        raise HTTPException(status_code=500, detail="관심공고를 수정하는 도중 서버 오류가 발생했습니다.")

@router.delete("/{bid_ntce_no}", summary="관심공고 삭제")
async def delete_favorite(bid_ntce_no: str, username: str = Depends(get_current_user), db: DatabaseManager = Depends(get_db)):
    """
    현재 로그인한 사용자의 관심공고에서 삭제합니다.
    """
    try:
        success = db.delete_favorite(username, bid_ntce_no)
        if not success:
            raise HTTPException(status_code=404, detail="삭제할 관심공고를 찾을 수 없습니다.")
        return {"message": "관심공고가 삭제되었습니다."}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("관심공고 삭제 실패: %s", e)
        raise HTTPException(status_code=500, detail="관심공고를 삭제하는 도중 서버 오류가 발생했습니다.")

@router.post("/sync", summary="로컬 스토리지 관심공고 동기화")
async def sync_favorites(
    request: FavoriteSyncRequest,
    username: str = Depends(get_current_user),
    db: DatabaseManager = Depends(get_db)
):
    """
    로그인 시 이전에 브라우저 로컬 스토리지(localStorage)에 임시 저장되었던 관심공고를
    현재 사용자의 서버 데이터베이스로 일괄 동기화(UPSERT)합니다.
    """
    synced_count = 0
    try:
        for fav in request.favorites:
            bid_no = fav.bid_ntce_no.strip()
            if not bid_no:
                continue
            db.add_favorite(
                username=username,
                bid_ntce_no=bid_no,
                status=fav.status,
                memo=fav.memo,
                partners=fav.partners,
                checklist=fav.checklist
            )
            if fav.title or fav.org_name:
                db.update_favorite(
                    username=username,
                    bid_ntce_no=bid_no,
                    title=fav.title,
                    org_name=fav.org_name,
                )
            synced_count += 1
        logger.info("관심공고 동기화 완료: %d건 [유저: %s]", synced_count, username)
        return {"message": f"{synced_count}개의 관심공고가 서버와 성공적으로 동기화되었습니다."}
    except Exception as e:
        logger.error("관심공고 동기화 실패: %s", e)
        raise HTTPException(status_code=500, detail="관심공고 동기화 작업 중 서버 오류가 발생했습니다.")


@router.get("/{bid_ntce_no}/recommend-partners", summary="공동 수급 컨소시엄 협업사 추천")
async def recommend_partners(
    bid_ntce_no: str,
    request: Request,
    username: str = Depends(get_current_user),
    db: DatabaseManager = Depends(get_db)
):
    """
    현재 공고의 자격 요건(면허, 지역)과 현재 활성 회사의 프로필을 대조하여
    부족한 자격을 충족해 줄 수 있는 타 기업 파트너를 지능적으로 추천합니다.
    """
    active_biz_id = request.headers.get("X-Active-Company")
    if not active_biz_id:
        # 회사 미등록 시 에러 대신 빈 결과 반환 (graceful fallback)
        return {
            "recommendations": [],
            "message": "사업자를 등록하면 맞춤 협업사 추천이 가능합니다.",
            "missing_licenses": [],
            "needs_region_match": False,
            "my_company": None
        }

    try:
        # 1. 공고 정보 가져오기
        bid_obj = db.get_bid_by_no(bid_ntce_no)
        if not bid_obj:
            raise HTTPException(status_code=404, detail="공고 정보를 찾을 수 없습니다.")
        bid = bid_obj.to_dict()

        # 2. 우리 회사 정보 가져오기
        my_company_obj = db.get_business(active_biz_id)
        if not my_company_obj:
            raise HTTPException(status_code=404, detail="자사 기업 프로필 정보를 찾을 수 없습니다.")
        my_company = my_company_obj.to_dict()

        # 3. 면허 및 지역 요건 분석
        req_licenses_str = bid.get("license_limit") or ""
        req_region = bid.get("region") or ""
        
        req_licenses = [l.strip() for l in req_licenses_str.split(",") if l.strip()]
        
        # 4. 자사 역량 분석
        my_licenses_str = my_company.get("licenses") or ""
        my_region_str = my_company.get("regions") or ""
        
        import json
        try:
            my_licenses = json.loads(my_licenses_str) if my_licenses_str.startswith("[") else [l.strip() for l in my_licenses_str.split(",") if l.strip()]
        except Exception:
            my_licenses = [my_licenses_str] if my_licenses_str else []

        try:
            my_regions = json.loads(my_region_str) if my_region_str.startswith("[") else [r.strip() for r in my_region_str.split(",") if r.strip()]
        except Exception:
            my_regions = [my_region_str] if my_region_str else []

        # 5. 부족한 면허 식별
        missing_licenses = [l for l in req_licenses if l not in my_licenses]
        
        # 지역 보완이 필요한지 판단
        needs_region_match = False
        if req_region and req_region != "전국" and req_region not in my_regions:
            needs_region_match = True

        recommendations = []
        
        # 6. 부족한 요건을 채워줄 다른 등록 기업 검색
        conn = db.get_connection()
        cursor = conn.execute(
            "SELECT biz_id, company_name, ceo_name, licenses, regions, annual_revenue, credit_rating FROM business_profiles WHERE biz_id != ? AND is_shared = 1",
            (active_biz_id,)
        )
        
        for row in cursor.fetchall():
            other = dict(row)
            other_licenses_str = other.get("licenses") or ""
            other_regions_str = other.get("regions") or ""
            
            try:
                other_licenses = json.loads(other_licenses_str) if other_licenses_str.startswith("[") else [l.strip() for l in other_licenses_str.split(",") if l.strip()]
            except Exception:
                other_licenses = [other_licenses_str] if other_licenses_str else []

            try:
                other_regions = json.loads(other_regions_str) if other_regions_str.startswith("[") else [r.strip() for r in other_regions_str.split(",") if r.strip()]
            except Exception:
                other_regions = [other_regions_str] if other_regions_str else []

            matched_reasons = []
            
            # 부족한 면허 보완 가능 여부
            supplied_licenses = [l for l in missing_licenses if l in other_licenses]
            if supplied_licenses:
                matched_reasons.append(f"부족한 면허 자격 보완: {', '.join(supplied_licenses)}")

            # 부족한 지역 요건 보완 가능 여부
            if needs_region_match and req_region in other_regions:
                matched_reasons.append(f"공고 지정 지역({req_region}) 소재 혜택 확보")

            if matched_reasons:
                recommendations.append({
                    "biz_id": other["biz_id"],
                    "company_name": other["company_name"],
                    "ceo_name": other["ceo_name"],
                    "credit_rating": other.get("credit_rating", "BBB"),
                    "matched_reasons": matched_reasons,
                    "licenses": other_licenses,
                    "regions": other_regions
                })

        return {
            "required_licenses": req_licenses,
            "required_region": req_region,
            "my_licenses": my_licenses,
            "my_regions": my_regions,
            "missing_licenses": missing_licenses,
            "needs_region_match": needs_region_match,
            "partners": recommendations[:5]
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("협업 파트너 추천 실패: %s", e)
        raise HTTPException(status_code=500, detail="협업 파트너를 매칭하는 도중 서버 오류가 발생했습니다.")
