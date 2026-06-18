"""
사업자 API 라우트

/businesses/* 엔드포인트: CRUD, 문서 업로드 및 자동 파싱
"""

import logging

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, Request

from ._helpers import get_db, get_current_user, _business_profile_to_api_dict, _load_settings
from src.config import load_config
from src.models.schemas import BusinessProfile

from src.models.database import DatabaseManager
from ._models import (
    BusinessCreateRequest, MemberAddRequest, MemberRoleUpdateRequest, 
    CafePostCreateRequest, CafeCommentCreateRequest,
    CollaborationProposalCreateRequest, CollaborationStatusUpdateRequest,
    CollaborationAiDraftRequest
)
from src.analyzers.llm_analyzer import LLMAnalyzer

logger = logging.getLogger(__name__)

router = APIRouter(tags=["businesses"])


# ──────────────────────────────────────────────
# 사업자 API
# ──────────────────────────────────────────────


@router.get("/businesses", summary="사업자 목록 조회")
async def get_businesses(username: str = Depends(get_current_user), db: DatabaseManager = Depends(get_db)):
    """
    등록된 현재 로그인한 사용자의 사업자 프로필 목록을 반환합니다.

    JSON 필드(business_types, licenses 등)는 파싱된 리스트로 반환됩니다.
    """
    try:
        profiles = db.get_businesses(username)
        return [_business_profile_to_api_dict(p) for p in profiles]
    except HTTPException:
        raise
    except Exception as e:
        logger.error("사업자 목록 조회 실패: %s [유저: %s]", e, username)
        raise HTTPException(status_code=500, detail="서버 내부 오류가 발생했습니다")


@router.post("/businesses", summary="사업자 등록", status_code=201)
async def create_business(
    request: BusinessCreateRequest,
    username: str = Depends(get_current_user),
    db: DatabaseManager = Depends(get_db)
):
    """
    새 사업자 프로필을 등록합니다.

    동일한 biz_id가 존재하면 덮어씁니다 (UPSERT).
    """
    try:
        # 입력 유효성 검증
        if not request.biz_id or not request.biz_id.strip():
            raise HTTPException(status_code=400, detail="사업자등록번호(biz_id)는 필수입니다.")
        if not request.company_name or not request.company_name.strip():
            raise HTTPException(status_code=400, detail="회사명(company_name)은 필수입니다.")

        # Pydantic 모델 → BusinessProfile dataclass 변환
        profile = BusinessProfile(
            biz_id=request.biz_id,
            company_name=request.company_name,
            username=username,
            ceo_name=request.ceo_name,
            business_types=request.business_types,
            licenses=request.licenses,
            regions=request.regions,
            past_projects=request.past_projects,
            annual_revenue=request.annual_revenue,
            employee_count=request.employee_count,
            keywords=request.keywords,
            min_budget=request.min_budget,
            max_budget=request.max_budget,
            is_shared=request.is_shared,
            website_url=request.website_url,
            intro_file_url=request.intro_file_url,
            social_links=request.social_links,
        )
        db.add_business(profile, username=username)
        logger.info("사업자 등록 완료: %s (%s) [유저: %s]", request.company_name, request.biz_id, username)

        return {
            "message": f"사업자 '{request.company_name}'이(가) 등록되었습니다.",
            "biz_id": request.biz_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("사업자 등록 실패: %s [유저: %s]", e, username)
        raise HTTPException(status_code=500, detail="서버 내부 오류가 발생했습니다")


def calculate_matching_score(my_profile: BusinessProfile, partner_profile: BusinessProfile) -> tuple[int, list[str]]:
    """자사와 파트너사 간의 협업 적합도 점수(0~100)와 매칭 사유를 연산합니다."""
    score = 50  # 기본 점수
    reasons = []
    
    # JSON 문자열 리스트 파싱 헬퍼
    import json
    def parse_list(val):
        if not val:
            return []
        if isinstance(val, list):
            return val
        try:
            parsed = json.loads(val)
            return parsed if isinstance(parsed, list) else [val]
        except Exception:
            # 쉼표 구분자 폴백
            return [v.strip() for v in str(val).split(",") if v.strip()]

    my_lic = parse_list(my_profile.licenses)
    other_lic = parse_list(partner_profile.licenses)
    
    # 1. 면허 상호보완성 분석
    unique_other_lic = [l for l in other_lic if l not in my_lic]
    if unique_other_lic:
        # 최대 25점 가산 (면허 개당 8점)
        points = min(len(unique_other_lic) * 8, 25)
        score += points
        reasons.append(f"자사에 없는 면허 자격({', '.join(unique_other_lic[:2])}) 보완 가능")
    
    # 2. 지역적 이점
    my_reg = parse_list(my_profile.regions)
    other_reg = parse_list(partner_profile.regions)
    different_reg = [r for r in other_reg if r not in my_reg]
    if different_reg:
        score += 10
        reasons.append(f"타 지역({', '.join(different_reg[:2])}) 소재 공고 입찰 가산점 확보")
    elif any(r in my_reg for r in other_reg):
        score += 5
        reasons.append("동일한 활동 권역으로 밀접한 현장 협업 가능")

    # 3. 신용등급 보너스
    credit_scores = {"AAA": 15, "AA+": 14, "AA": 13, "AA-": 12, "A+": 11, "A": 10, "A-": 9, "BBB+": 8, "BBB": 7, "BBB-": 6}
    my_credit_val = credit_scores.get(my_profile.credit_rating, 5)
    other_credit_val = credit_scores.get(partner_profile.credit_rating, 5)
    
    if other_credit_val > my_credit_val:
        score += 10
        reasons.append(f"상대적으로 우수한 신용등급({partner_profile.credit_rating})을 활용한 입찰 심사 가점")
    
    # 4. 실적 규모 보완
    my_rev = my_profile.annual_revenue or 0
    other_rev = partner_profile.annual_revenue or 0
    if other_rev > 0:
        if my_rev > 0 and other_rev > my_rev:
            score += 10
            reasons.append("대규모 사업 입찰을 위한 연 매출 실적 보완")
        else:
            score += 5
            reasons.append("수행 실적 기반의 안정적인 공동 컨소시엄 구축")

    score = max(50, min(score, 100))
    return int(score), reasons


@router.get("/businesses/shared", summary="정보 공유 동의 기업 목록 조회")
async def get_shared_businesses(
    request: Request,
    username: str = Depends(get_current_user),
    db: DatabaseManager = Depends(get_db)
):
    """
    정보 공유에 동의한 타 회원사 목록을 반환합니다.
    자사 활성 회사(X-Active-Company 헤더) 기준 협업 궁합도 점수와 매칭 사유도 함께 연산하여 제공합니다.
    """
    try:
        profiles = db.get_shared_businesses()
        
        # 활성 회사 프로필 로드
        active_biz_id = request.headers.get("X-Active-Company")
        my_profile = None
        if active_biz_id:
            my_profile = db.get_business(active_biz_id)

        results = []
        for p in profiles:
            p_dict = _business_profile_to_api_dict(p)
            
            # 자사 활성 회사와의 매칭 궁합 점수 및 사유 연산
            if my_profile and p.biz_id != active_biz_id:
                score, reasons = calculate_matching_score(my_profile, p)
                p_dict["match_score"] = score
                p_dict["match_reasons"] = reasons
            else:
                p_dict["match_score"] = None
                p_dict["match_reasons"] = []
                
            results.append(p_dict)
            
        return results
    except Exception as e:
        logger.error("공유 기업 목록 조회 실패: %s [유저: %s]", e, username)
        raise HTTPException(status_code=500, detail="공유 기업 목록 조회에 실패했습니다.")


@router.get("/businesses/{biz_id}", summary="사업자 상세 조회")
async def get_business(
    biz_id: str,
    username: str = Depends(get_current_user),
    db: DatabaseManager = Depends(get_db)
):
    """
    특정 사업자의 상세 프로필 정보를 반환합니다.
    """
    try:
        profile = db.get_business(biz_id, username)
        if not profile:
            raise HTTPException(
                status_code=404,
                detail=f"사업자를 찾을 수 없습니다: {biz_id}",
            )
        return _business_profile_to_api_dict(profile)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("사업자 상세 조회 실패: %s [유저: %s]", e, username)
        raise HTTPException(status_code=500, detail="서버 내부 오류가 발생했습니다")


@router.put("/businesses/{biz_id}", summary="사업자 수정")
async def update_business(
    biz_id: str,
    request: BusinessCreateRequest,
    username: str = Depends(get_current_user),
    db: DatabaseManager = Depends(get_db)
):
    """
    기존 사업자 프로필을 수정합니다.

    경로의 biz_id와 본문의 biz_id가 일치해야 합니다.
    """
    if biz_id != request.biz_id:
        raise HTTPException(
            status_code=400,
            detail="경로의 biz_id와 요청 본문의 biz_id가 일치하지 않습니다.",
        )

    try:
        # 기존 프로필 존재 여부 확인 및 권한 검증
        role = db.get_business_user_role(biz_id, username)
        if not role or role not in ("owner", "admin"):
            raise HTTPException(
                status_code=403,
                detail="회사 프로필을 수정할 권한이 없습니다. (owner 또는 admin 권한 필요)"
            )
            
        existing = db.get_business(biz_id, username)
        if not existing:
            raise HTTPException(
                status_code=404,
                detail=f"사업자를 찾을 수 없습니다: {biz_id}",
            )

        profile = BusinessProfile(
            biz_id=request.biz_id,
            company_name=request.company_name,
            username=username,
            ceo_name=request.ceo_name,
            business_types=request.business_types,
            licenses=request.licenses,
            regions=request.regions,
            past_projects=request.past_projects,
            annual_revenue=request.annual_revenue,
            employee_count=request.employee_count,
            keywords=request.keywords,
            min_budget=request.min_budget,
            max_budget=request.max_budget,
            is_shared=request.is_shared,
            website_url=request.website_url,
            intro_file_url=request.intro_file_url,
            social_links=request.social_links,
        )

        success = db.update_business(profile)
        if not success:
            raise HTTPException(status_code=500, detail="사업자 수정에 실패했습니다.")

        logger.info("사업자 수정 완료: %s [유저: %s]", biz_id, username)
        return {"message": f"사업자 '{request.company_name}'이(가) 수정되었습니다."}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("사업자 수정 실패: %s [유저: %s]", e, username)
        raise HTTPException(status_code=500, detail="서버 내부 오류가 발생했습니다")


@router.delete("/businesses/{biz_id}", summary="사업자 삭제")
async def delete_business(
    biz_id: str,
    username: str = Depends(get_current_user),
    db: DatabaseManager = Depends(get_db)
):
    """사업자 프로필을 삭제합니다."""
    try:
        success = db.delete_business(biz_id, username)
        if not success:
            raise HTTPException(
                status_code=404,
                detail=f"사업자를 찾을 수 없습니다: {biz_id}",
            )

        logger.info("사업자 삭제 완료: %s [유저: %s]", biz_id, username)
        return {"message": f"사업자 '{biz_id}'이(가) 삭제되었습니다."}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("사업자 삭제 실패: %s [유저: %s]", e, username)
        raise HTTPException(status_code=500, detail="서버 내부 오류가 발생했습니다")


# ──────────────────────────────────────────────
# 사업자 문서 업로드 및 자동 파싱 API
# ──────────────────────────────────────────────


@router.post("/businesses/parse-doc", summary="사업자 문서 업로드 → 자동 정보 추출")
async def parse_business_document(
    file: UploadFile = File(..., description="사업자등록증 또는 재무제표 파일"),
    doc_type: str = Query("auto", description="문서 유형: registration, financial, auto"),
):
    """
    사업자등록증 또는 재무제표를 업로드하면 AI가 자동으로 정보를 추출합니다.

    지원 형식:
      - PDF (.pdf)
      - 이미지 (.jpg, .png, .jpeg) — OpenAI API 키 설정 시 Vision 인식
      - HWP (.hwp)
      - 텍스트 (.txt)

    Returns:
        추출된 사업자 정보 (사업자번호, 회사명, 대표자, 업종, 지역 등)
    """
    # 파일 크기 제한 (20MB)
    MAX_SIZE = 20 * 1024 * 1024
    content = await file.read()
    if len(content) > MAX_SIZE:
        raise HTTPException(status_code=413, detail="파일 크기가 20MB를 초과합니다.")

    filename = file.filename or "unknown.pdf"
    logger.info("사업자 문서 업로드: %s (%d bytes, type=%s)", filename, len(content), doc_type)

    try:
        from src.parsers.business_doc_parser import BusinessDocParser

        config = load_config()
        user_settings = _load_settings()
        llm_engine = user_settings.get('llm_engine', getattr(config, 'llm_engine', 'gemini'))
        parser = BusinessDocParser(
            openai_api_key=config.openai_api_key,
            gemini_api_key=getattr(config, 'gemini_api_key', ''),
            engine=llm_engine,
        )
        result = parser.parse_business_doc(content, filename, doc_type)

        logger.info(
            "문서 파싱 완료: %s (confidence=%s, biz_id=%s, company=%s)",
            filename, result.get('confidence'), result.get('biz_id'), result.get('company_name'),
        )
        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error("문서 파싱 실패: %s — %s", filename, e)
        raise HTTPException(status_code=500, detail="서버 내부 오류가 발생했습니다")


@router.post("/businesses/parse-docs", summary="복수 문서 업로드 → 정보 병합")
async def parse_multiple_business_docs(
    files: list[UploadFile] = File(..., description="사업자등록증 + 재무제표 등 복수 파일"),
):
    """
    여러 문서를 한 번에 업로드하여 정보를 병합합니다.
    사업자등록증에서 기본 정보를, 재무제표에서 매출/직원 수를 추출하여 합칩니다.
    """
    MAX_SIZE = 20 * 1024 * 1024
    skipped_files = []
    merged = {
        'biz_id': '', 'company_name': '', 'ceo_name': '',
        'business_types': [], 'licenses': [], 'regions': [],
        'annual_revenue': 0, 'employee_count': 0, 'keywords': [],
        'confidence': 'low', 'parsed_files': [],
    }

    try:
        from src.parsers.business_doc_parser import BusinessDocParser

        config = load_config()
        user_settings = _load_settings()
        llm_engine = user_settings.get('llm_engine', getattr(config, 'llm_engine', 'gemini'))
        parser = BusinessDocParser(
            openai_api_key=config.openai_api_key,
            gemini_api_key=getattr(config, 'gemini_api_key', ''),
            engine=llm_engine,
        )

        for f in files:
            content = await f.read()
            if len(content) > MAX_SIZE:
                skipped_files.append(f.filename or "unknown")
                continue

            filename = f.filename or "unknown"
            result = parser.parse_business_doc(content, filename, 'auto')

            # 병합 (비어있지 않은 값만 덮어쓰기)
            if result.get('biz_id') and not merged['biz_id']:
                merged['biz_id'] = result['biz_id']
            if result.get('company_name') and not merged['company_name']:
                merged['company_name'] = result['company_name']
            if result.get('ceo_name') and not merged['ceo_name']:
                merged['ceo_name'] = result['ceo_name']
            if result.get('business_types'):
                merged['business_types'] = list(set(merged['business_types'] + result['business_types']))
            if result.get('licenses'):
                merged['licenses'] = list(set(merged['licenses'] + result['licenses']))
            if result.get('regions'):
                merged['regions'] = list(set(merged['regions'] + result['regions']))
            if result.get('keywords'):
                merged['keywords'] = list(set(merged['keywords'] + result['keywords']))
            if result.get('annual_revenue') and not merged['annual_revenue']:
                merged['annual_revenue'] = result['annual_revenue']
            if result.get('employee_count') and not merged['employee_count']:
                merged['employee_count'] = result['employee_count']

            merged['parsed_files'].append({
                'filename': filename,
                'doc_type': result.get('doc_type', 'unknown'),
                'confidence': result.get('confidence', 'low'),
            })

        # 최종 신뢰도
        filled = sum(1 for v in [merged['biz_id'], merged['company_name'], merged['annual_revenue']] if v)
        merged['confidence'] = 'high' if filled >= 2 else 'medium' if filled >= 1 else 'low'

        if skipped_files:
            merged['skipped_files'] = skipped_files

        return merged

    except HTTPException:
        raise
    except Exception as e:
        logger.error("복수 문서 파싱 실패: %s", e)
        raise HTTPException(status_code=500, detail="서버 내부 오류가 발생했습니다")


# ──────────────────────────────────────────────
# 다중 회사 조직 및 멤버(직원) 관리 API
# ──────────────────────────────────────────────

@router.get("/companies/my", summary="내 소속 회사 목록 조회")
async def get_my_companies(
    username: str = Depends(get_current_user),
    db: DatabaseManager = Depends(get_db)
):
    """현재 로그인한 사용자가 소속된 모든 회사 및 멤버 역할 정보를 가져옵니다."""
    try:
        return db.get_user_companies(username)
    except Exception as e:
        logger.error("내 소속 회사 목록 조회 실패: %s [유저: %s]", e, username)
        raise HTTPException(status_code=500, detail="소속 회사 목록을 가져오는 도중 오류가 발생했습니다.")


@router.get("/companies/{biz_id}/members", summary="회사 멤버 목록 조회")
async def get_members(
    biz_id: str,
    username: str = Depends(get_current_user),
    db: DatabaseManager = Depends(get_db)
):
    """현재 활성화된 회사의 소속 직원 목록을 조회합니다 (회사 멤버만 허용)."""
    try:
        role = db.get_business_user_role(biz_id, username)
        if not role:
            raise HTTPException(status_code=403, detail="해당 회사의 멤버 목록 조회 권한이 없습니다.")
            
        return db.get_business_members(biz_id)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("회사 멤버 조회 실패: %s [회사: %s]", e, biz_id)
        raise HTTPException(status_code=500, detail="직원 목록 조회 도중 오류가 발생했습니다.")


@router.post("/companies/{biz_id}/members", summary="회사 직원 등록 (초대)")
async def add_member(
    biz_id: str,
    req: MemberAddRequest,
    username: str = Depends(get_current_user),
    db: DatabaseManager = Depends(get_db)
):
    """회사의 대표(owner) 또는 관리자(admin)가 타 회원을 자사 직원으로 초대 등록합니다."""
    try:
        my_role = db.get_business_user_role(biz_id, username)
        if not my_role or my_role not in ("owner", "admin"):
            raise HTTPException(status_code=403, detail="직원을 추가할 권한이 없습니다. (owner/admin 권한 필요)")
            
        target_user = req.username.strip()
        user_info = db.get_user(target_user)
        if not user_info:
            raise HTTPException(status_code=404, detail="존재하지 않는 사용자 아이디입니다.")
            
        success = db.add_business_member(biz_id, target_user, req.role)
        if not success:
            raise HTTPException(status_code=400, detail="이미 등록된 직원이거나 등록에 실패했습니다.")
            
        return {"message": f"직원 '{target_user}'이(가) 등록되었습니다."}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("직원 등록 실패: %s [회사: %s]", e, biz_id)
        raise HTTPException(status_code=500, detail="직원을 추가하는 도중 서버 오류가 발생했습니다.")


@router.put("/companies/{biz_id}/members/{target_username}", summary="직원 역할 수정")
async def update_member_role(
    biz_id: str,
    target_username: str,
    req: MemberRoleUpdateRequest,
    username: str = Depends(get_current_user),
    db: DatabaseManager = Depends(get_db)
):
    """회사의 대표(owner) 또는 관리자(admin)가 직원의 역할을 수정합니다."""
    try:
        my_role = db.get_business_user_role(biz_id, username)
        if not my_role or my_role not in ("owner", "admin"):
            raise HTTPException(status_code=403, detail="직원 권한을 수정할 권한이 없습니다.")
            
        if target_username == username:
            raise HTTPException(status_code=400, detail="본인의 역할은 스스로 수정할 수 없습니다.")
            
        success = db.update_business_member_role(biz_id, target_username, req.role)
        if not success:
            raise HTTPException(status_code=404, detail="수정할 대상을 찾을 수 없거나 권한 변경에 실패했습니다.")
            
        return {"message": f"직원 '{target_username}'의 역할이 '{req.role}'(으)로 변경되었습니다."}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("직원 권한 수정 실패: %s [회사: %s]", e, biz_id)
        raise HTTPException(status_code=500, detail="역할 수정 도중 서버 오류가 발생했습니다.")


@router.delete("/companies/{biz_id}/members/{target_username}", summary="직원 삭제 (퇴사)")
async def remove_member(
    biz_id: str,
    target_username: str,
    username: str = Depends(get_current_user),
    db: DatabaseManager = Depends(get_db)
):
    """회사의 대표(owner) 또는 관리자(admin)가 직원을 조직에서 제거(퇴사 처리)합니다."""
    try:
        my_role = db.get_business_user_role(biz_id, username)
        if not my_role or my_role not in ("owner", "admin"):
            raise HTTPException(status_code=403, detail="직원을 제외할 권한이 없습니다.")
            
        if target_username == username:
            raise HTTPException(status_code=400, detail="스스로 퇴사할 수 없습니다. (회사 삭제를 이용해 주세요)")
            
        success = db.remove_business_member(biz_id, target_username)
        if not success:
            raise HTTPException(status_code=404, detail="제외할 직원을 찾을 수 없습니다.")
            
        return {"message": f"직원 '{target_username}'이(가) 회사에서 제외되었습니다."}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("직원 제외 실패: %s [회사: %s]", e, biz_id)
        raise HTTPException(status_code=500, detail="직원을 제외하는 도중 서버 오류가 발생했습니다.")


# ──────────────────────────────────────────────
# 사내 카페(커뮤니티) API
# ──────────────────────────────────────────────

@router.get("/companies/{biz_id}/cafe", summary="사내 카페 게시글 목록 조회")
async def list_cafe_posts(
    biz_id: str,
    username: str = Depends(get_current_user),
    db: DatabaseManager = Depends(get_db)
):
    """소속 회사의 사내 카페 게시판 목록을 조회합니다."""
    role = db.get_business_user_role(biz_id, username)
    if not role:
        raise HTTPException(status_code=403, detail="해당 회사 소속 멤버만 카페를 이용할 수 있습니다.")
    
    return db.get_cafe_posts(biz_id, username)


@router.post("/companies/{biz_id}/cafe", summary="사내 카페 게시글 등록", status_code=201)
async def write_cafe_post(
    biz_id: str,
    req: CafePostCreateRequest,
    username: str = Depends(get_current_user),
    db: DatabaseManager = Depends(get_db)
):
    """사내 카페에 새로운 게시글을 등록합니다."""
    role = db.get_business_user_role(biz_id, username)
    if not role:
        raise HTTPException(status_code=403, detail="해당 회사 소속 멤버만 카페에 글을 쓸 수 있습니다.")
    
    post = db.create_cafe_post(biz_id, username, req.title, req.content)
    if not post:
        raise HTTPException(status_code=500, detail="게시글 등록에 실패했습니다.")
        
    return post


@router.delete("/companies/{biz_id}/cafe/{post_id}", summary="사내 카페 게시글 삭제")
async def remove_cafe_post(
    biz_id: str,
    post_id: int,
    username: str = Depends(get_current_user),
    db: DatabaseManager = Depends(get_db)
):
    """작성자 본인 또는 회사 대표(owner)/관리자(admin)가 게시글을 삭제합니다."""
    role = db.get_business_user_role(biz_id, username)
    if not role:
        raise HTTPException(status_code=403, detail="해당 회사 소속 멤버가 아닙니다.")
    
    # 게시글 조회하여 작성자 본인인지 확인
    posts = db.get_cafe_posts(biz_id, username)
    post = next((p for p in posts if p["id"] == post_id), None)
    if not post:
        raise HTTPException(status_code=404, detail="게시글이 존재하지 않습니다.")
        
    # 작성자 본인이거나 회사의 owner/admin인지 권한 체크
    is_author = post["username"] == username
    is_manager = role in ("owner", "admin")
    
    if not is_author and not is_manager:
        raise HTTPException(status_code=403, detail="본인이 작성한 글이거나 관리자 권한이 있어야 삭제할 수 있습니다.")
        
    success = db.delete_cafe_post(post_id, biz_id)
    if not success:
        raise HTTPException(status_code=500, detail="게시글 삭제에 실패했습니다.")
        
    return {"message": "게시글이 삭제되었습니다."}


@router.get("/companies/{biz_id}/cafe/{post_id}/comments", summary="사내 카페 게시글 댓글 조회")
async def list_cafe_comments(
    biz_id: str,
    post_id: int,
    username: str = Depends(get_current_user),
    db: DatabaseManager = Depends(get_db)
):
    """특정 게시글의 댓글 목록을 조회합니다."""
    role = db.get_business_user_role(biz_id, username)
    if not role:
        raise HTTPException(status_code=403, detail="해당 회사 소속 멤버만 댓글을 볼 수 있습니다.")
    
    return db.get_cafe_comments(post_id)


@router.post("/companies/{biz_id}/cafe/{post_id}/comments", summary="사내 카페 게시글 댓글 등록", status_code=201)
async def write_cafe_comment(
    biz_id: str,
    post_id: int,
    req: CafeCommentCreateRequest,
    username: str = Depends(get_current_user),
    db: DatabaseManager = Depends(get_db)
):
    """게시글에 댓글을 추가합니다."""
    role = db.get_business_user_role(biz_id, username)
    if not role:
        raise HTTPException(status_code=403, detail="해당 회사 소속 멤버만 댓글을 쓸 수 있습니다.")
    
    comment = db.create_cafe_comment(post_id, username, req.content)
    if not comment:
        raise HTTPException(status_code=500, detail="댓글 작성에 실패했습니다.")
        
    return comment


@router.delete("/companies/{biz_id}/cafe/{post_id}/comments/{comment_id}", summary="사내 카페 게시글 댓글 삭제")
async def remove_cafe_comment(
    biz_id: str,
    post_id: int,
    comment_id: int,
    username: str = Depends(get_current_user),
    db: DatabaseManager = Depends(get_db)
):
    """본인의 댓글 또는 회사 대표/관리자가 댓글을 삭제합니다."""
    role = db.get_business_user_role(biz_id, username)
    if not role:
        raise HTTPException(status_code=403, detail="해당 회사 소속 멤버가 아닙니다.")
        
    comments = db.get_cafe_comments(post_id)
    comment = next((c for c in comments if c["id"] == comment_id), None)
    if not comment:
        raise HTTPException(status_code=404, detail="댓글이 존재하지 않습니다.")
        
    is_author = comment["username"] == username
    is_manager = role in ("owner", "admin")
    
    if not is_author and not is_manager:
        raise HTTPException(status_code=403, detail="본인의 댓글이거나 관리자 권한이 있어야 삭제할 수 있습니다.")
        
    success = db.delete_cafe_comment(comment_id, username, is_admin=is_manager)
    if not success:
        raise HTTPException(status_code=500, detail="댓글 삭제에 실패했습니다.")
        
    return {"message": "댓글이 삭제되었습니다."}


@router.post("/companies/{biz_id}/cafe/{post_id}/like", summary="사내 카페 게시글 좋아요 토글")
async def toggle_cafe_post_like(
    biz_id: str,
    post_id: int,
    username: str = Depends(get_current_user),
    db: DatabaseManager = Depends(get_db)
):
    """게시글의 좋아요를 누르거나 취소합니다."""
    role = db.get_business_user_role(biz_id, username)
    if not role:
        raise HTTPException(status_code=403, detail="해당 회사 소속 멤버만 좋아요를 누를 수 있습니다.")
        
    result = db.toggle_cafe_post_like(post_id, username)
    if not result.get("success"):
        raise HTTPException(status_code=500, detail="좋아요 처리에 실패했습니다.")
        
    return result

@router.put("/companies/{biz_id}/cafe/{post_id}", summary="사내 카페 게시글 수정")
async def edit_cafe_post(
    biz_id: str,
    post_id: int,
    req: CafePostCreateRequest,
    username: str = Depends(get_current_user),
    db: DatabaseManager = Depends(get_db)
):
    """본인이 작성한 게시글의 제목과 내용을 수정합니다."""
    role = db.get_business_user_role(biz_id, username)
    if not role:
        raise HTTPException(status_code=403, detail="해당 회사 소속 멤버가 아닙니다.")

    # 게시글 존재 및 본인 확인
    posts = db.get_cafe_posts(biz_id, username)
    post = next((p for p in posts if p["id"] == post_id), None)
    if not post:
        raise HTTPException(status_code=404, detail="게시글이 존재하지 않습니다.")
    if post["username"] != username:
        raise HTTPException(status_code=403, detail="본인이 작성한 게시글만 수정할 수 있습니다.")

    if not req.title.strip() or not req.content.strip():
        raise HTTPException(status_code=400, detail="제목과 내용을 모두 입력해 주세요.")

    success = db.update_cafe_post(post_id, biz_id, username, req.title.strip(), req.content.strip())
    if not success:
        raise HTTPException(status_code=500, detail="게시글 수정에 실패했습니다.")

    return {"message": "게시글이 수정되었습니다."}




@router.post("/businesses/proposals", summary="공동 수급/협업 제안 전송")
async def create_collaboration_proposal(
    request: CollaborationProposalCreateRequest,
    username: str = Depends(get_current_user),
    db: DatabaseManager = Depends(get_db)
):
    """
    타 회원사에게 특정 입찰 공고 공동수급 협업 제안을 발송합니다.
    """
    try:
        # 권한 검증: 보낸 biz_id의 소유자/멤버인지 확인
        role = db.get_business_user_role(request.sender_biz_id, username)
        if not role:
            raise HTTPException(status_code=403, detail="제안을 보낼 권한이 없습니다. (해당 회사 멤버 아님)")

        # 자기 자신에게 보내는 제안 차단
        if request.sender_biz_id == request.receiver_biz_id:
            raise HTTPException(status_code=400, detail="자기 자신의 회사에는 제안을 보낼 수 없습니다.")

        # 수신 회사 존재 여부 확인
        receiver_biz = db.get_business(request.receiver_biz_id)
        if not receiver_biz:
            raise HTTPException(status_code=404, detail="수신 회사가 존재하지 않습니다.")

        success = db.send_collaboration_proposal(
            sender_biz_id=request.sender_biz_id,
            receiver_biz_id=request.receiver_biz_id,
            bid_ntce_no=request.bid_ntce_no,
            message=request.message
        )
        if not success:
            raise HTTPException(status_code=500, detail="협업 제안 전송에 실패했습니다.")
            
        return {"message": "협업 제안이 성공적으로 전송되었습니다."}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("협업 제안 전송 실패: %s [유저: %s]", e, username)
        raise HTTPException(status_code=500, detail="서버 내부 오류가 발생했습니다.")


@router.get("/businesses/proposals/received", summary="받은 협업 제안 목록 조회")
async def get_received_proposals(
    biz_id: str = Query(..., description="조회할 회사 ID"),
    username: str = Depends(get_current_user),
    db: DatabaseManager = Depends(get_db)
):
    """
    특정 내 회사가 수신한 모든 협업 제안 목록을 조회합니다.
    """
    try:
        role = db.get_business_user_role(biz_id, username)
        if not role:
            raise HTTPException(status_code=403, detail="조회 권한이 없습니다. (해당 회사 멤버 아님)")
            
        proposals = db.get_received_proposals(biz_id)
        return proposals
    except HTTPException:
        raise
    except Exception as e:
        logger.error("수신 협업 제안 조회 실패: %s [유저: %s]", e, username)
        raise HTTPException(status_code=500, detail="서버 내부 오류가 발생했습니다.")


@router.get("/businesses/proposals/sent", summary="보낸 협업 제안 목록 조회")
async def get_sent_proposals(
    biz_id: str = Query(..., description="조회할 회사 ID"),
    username: str = Depends(get_current_user),
    db: DatabaseManager = Depends(get_db)
):
    """
    특정 내 회사가 타사에 발송한 모든 협업 제안 목록을 조회합니다.
    """
    try:
        role = db.get_business_user_role(biz_id, username)
        if not role:
            raise HTTPException(status_code=403, detail="조회 권한이 없습니다. (해당 회사 멤버 아님)")
            
        proposals = db.get_sent_proposals(biz_id)
        return proposals
    except HTTPException:
        raise
    except Exception as e:
        logger.error("송신 협업 제안 조회 실패: %s [유저: %s]", e, username)
        raise HTTPException(status_code=500, detail="서버 내부 오류가 발생했습니다.")


@router.put("/businesses/proposals/{proposal_id}/status", summary="협업 제안 상태 변경 (수락/거절)")
async def update_proposal_status(
    proposal_id: int,
    request: CollaborationStatusUpdateRequest,
    username: str = Depends(get_current_user),
    db: DatabaseManager = Depends(get_db)
):
    """
    수신한 협업 제안을 수락(accepted)하거나 거절(rejected) 처리합니다.
    """
    try:
        # 이 제안이 로그인한 유저의 회사에 온 것인지 확인하기 위해, 수신사 ID(receiver_biz_id)에 대해 권한이 있는지 체크
        conn = db.get_connection()
        ph = "%s" if db.is_postgres else "?"
        cursor = conn.execute(f"SELECT receiver_biz_id FROM collaboration_proposals WHERE id = {ph}", (proposal_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="해당 협업 제안을 찾을 수 없습니다.")
            
        receiver_biz_id = row[0]
        role = db.get_business_user_role(receiver_biz_id, username)
        if not role or role not in ("owner", "admin"):
            raise HTTPException(status_code=403, detail="제안 수락/거절은 해당 회사의 관리자(owner/admin)만 가능합니다.")

        if request.status not in ("accepted", "rejected"):
            raise HTTPException(status_code=400, detail="상태값은 'accepted' 또는 'rejected'만 가능합니다.")
            
        success = db.update_proposal_status(proposal_id, request.status)
        if not success:
            raise HTTPException(status_code=500, detail="제안 상태 변경에 실패했습니다.")
            
        status_kor = "수락" if request.status == "accepted" else "거절"
        return {"message": f"제안이 {status_kor}되었습니다."}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("제안 상태 변경 실패: %s [유저: %s]", e, username)
        raise HTTPException(status_code=500, detail="서버 내부 오류가 발생했습니다.")


@router.post("/businesses/proposals/ai-draft", summary="협업 제안서 AI 초안 작성")
async def generate_collaboration_proposal_ai_draft(
    request: CollaborationAiDraftRequest,
    username: str = Depends(get_current_user),
    db: DatabaseManager = Depends(get_db)
):
    """
    대상 공고와 송/수신 회원사의 프로필 역량을 비교 분석하여, 맞춤형 협업 제안서 초안 텍스트를 AI 또는 룰 기반으로 생성합니다.
    """
    try:
        # 권한 확인
        role = db.get_business_user_role(request.sender_biz_id, username)
        if not role:
            raise HTTPException(status_code=403, detail="제안서 초안을 작성할 권한이 없습니다. (해당 회사 멤버 아님)")

        sender = db.get_business(request.sender_biz_id)
        receiver = db.get_business(request.receiver_biz_id)
        bid = db.get_bid_by_no(request.bid_ntce_no)

        if not sender or not receiver:
            raise HTTPException(status_code=404, detail="사업자 프로필 정보를 조회할 수 없습니다.")
        if not bid:
            raise HTTPException(status_code=404, detail="입찰 공고 정보를 조회할 수 없습니다.")

        # 폴백 템플릿 제안서 (API 키 누락 시 혹은 에러 시 사용)
        fallback_draft = (
            f"안녕하세요, {receiver.company_name} 대표님.\n"
            f"{sender.company_name}에서 공동수급 참여를 정중히 제안드립니다.\n\n"
            f"저희가 검토 중인 입찰 공고인 '{bid.title}'(공고번호: {bid.bid_ntce_no})에 대해, "
            f"양사의 역량을 합쳐 컨소시엄을 구성하고자 합니다.\n\n"
            f"특히, 이번 사업의 요구 조건인 '{bid.license_limit or '면허 사항'}'과 관련하여 "
            f"귀사가 보유하신 우수한 면허/실적 역량이 큰 강점이 될 것으로 판단됩니다. "
            f"저희 {sender.company_name}의 기술력 및 수행력과 귀사의 면허/지역적 이점을 결합한다면, "
            f"적격심사 가산점 확보는 물론 투찰 성공률을 비약적으로 높일 수 있을 것입니다.\n\n"
            f"공동수급 비율 및 구체적인 협력 조건(공동이행방식 또는 분담이행방식)에 대해서는 "
            f"긍정적으로 협의 가능하오니 검토 후 회신 부탁드립니다. 감사합니다."
        )

        # AI 초안 생성 시도 (Gemini 또는 OpenAI 설정 확인)
        config = load_config()
        user_settings = db.get_user_ai_settings(username)
        user_settings_dict = user_settings if user_settings else {}
        llm_engine = user_settings_dict.get('llm_engine', getattr(config, 'llm_engine', 'gemini'))
        
        has_llm = False
        api_key = ""
        model_name = "gemini-2.5-flash"
        
        if llm_engine == "gemini":
            api_key = getattr(config, "gemini_api_key", "")
            model_name = getattr(config, "gemini_model", "gemini-2.5-flash")
            has_llm = bool(api_key)
        else:
            api_key = getattr(config, "openai_api_key", "")
            model_name = getattr(config, "openai_model", "gpt-4o-mini")
            has_llm = bool(api_key)

        if not has_llm:
            logger.info("API 키 미설정으로 협업 제안서 룰 기반 템플릿 제공 [유저: %s]", username)
            return {"draft": fallback_draft, "source": "template"}

        try:
            # 프롬프트 조립
            prompt = (
                f"당신은 대한민국 공공입찰 컨소시엄 및 공동수급 기획 비서입니다.\n"
                f"다음 정보를 기반으로 정중하고 전문적인 '공동수급체 구성 제안 메시지'를 한글로 작성해 주세요.\n\n"
                f"[송신 회사(제안사)]\n"
                f"- 회사명: {sender.company_name}\n"
                f"- 보유면허: {sender.licenses}\n"
                f"- 활동지역: {sender.regions}\n\n"
                f"[수신 회사(대상사)]\n"
                f"- 회사명: {receiver.company_name}\n"
                f"- 보유면허: {receiver.licenses}\n"
                f"- 활동지역: {receiver.regions}\n\n"
                f"[대상 입찰공고]\n"
                f"- 공고명: {bid.title}\n"
                f"- 공고번호: {bid.bid_ntce_no}\n"
                f"- 요구 면허/지역제한: {bid.license_limit or '없음'} / {bid.region or '전국'}\n\n"
                f"[메시지 요구사항]\n"
                f"1. 수신사의 강점(예: 면허 보완, 지역 이점 등)을 언급하며 공동 수급으로 참여했을 때 상호 윈-윈할 수 있는 포인트를 강조해 주세요.\n"
                f"2. 분량은 공백 포함 300~500자 내외로 너무 길지 않고 정중하며 간결하게 작성해 주세요.\n"
                f"3. '~하고자 제안드립니다.' 형태로 격식 있고 신뢰감 있게 표현해 주세요. 인사는 빼고 핵심 메시지만 작성해 주세요."
            )

            analyzer = LLMAnalyzer(api_key=api_key, model=model_name, engine=llm_engine)
            response_text = analyzer.generate(prompt)
            if response_text and len(response_text.strip()) > 50:
                return {"draft": response_text.strip(), "source": "ai"}
            else:
                return {"draft": fallback_draft, "source": "template_fallback"}
        except Exception as ai_err:
            logger.warning("AI 제안서 초안 생성 중 오류 발생, 템플릿으로 대체: %s", ai_err)
            return {"draft": fallback_draft, "source": "template_error"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error("협업 제안서 초안 작성 실패: %s [유저: %s]", e, username)
        raise HTTPException(status_code=500, detail="서버 내부 오류가 발생했습니다.")
