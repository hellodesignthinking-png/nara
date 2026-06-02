"""
사업자 API 라우트

/businesses/* 엔드포인트: CRUD, 문서 업로드 및 자동 파싱
"""

import logging

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile

from src.config import load_config
from src.models.schemas import BusinessProfile

from ._helpers import get_db, _business_profile_to_api_dict, _load_settings
from ._models import BusinessCreateRequest

logger = logging.getLogger(__name__)

router = APIRouter(tags=["businesses"])


# ──────────────────────────────────────────────
# 사업자 API
# ──────────────────────────────────────────────


@router.get("/businesses", summary="사업자 목록 조회")
async def get_businesses(db=Depends(get_db)):
    """
    등록된 전체 사업자 프로필 목록을 반환합니다.

    JSON 필드(business_types, licenses 등)는 파싱된 리스트로 반환됩니다.
    """
    try:
        profiles = db.get_businesses()
        return [_business_profile_to_api_dict(p) for p in profiles]
    except HTTPException:
        raise
    except Exception as e:
        logger.error("사업자 목록 조회 실패: %s", e)
        raise HTTPException(status_code=500, detail="서버 내부 오류가 발생했습니다")


@router.post("/businesses", summary="사업자 등록", status_code=201)
async def create_business(request: BusinessCreateRequest, db=Depends(get_db)):
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
        )
        db.add_business(profile)
        logger.info("사업자 등록 완료: %s (%s)", request.company_name, request.biz_id)

        return {
            "message": f"사업자 '{request.company_name}'이(가) 등록되었습니다.",
            "biz_id": request.biz_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("사업자 등록 실패: %s", e)
        raise HTTPException(status_code=500, detail="서버 내부 오류가 발생했습니다")


@router.put("/businesses/{biz_id}", summary="사업자 수정")
async def update_business(biz_id: str, request: BusinessCreateRequest, db=Depends(get_db)):
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
        # 기존 프로필 존재 여부 확인
        existing = db.get_business(biz_id)
        if not existing:
            raise HTTPException(
                status_code=404,
                detail=f"사업자를 찾을 수 없습니다: {biz_id}",
            )

        profile = BusinessProfile(
            biz_id=request.biz_id,
            company_name=request.company_name,
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
        )

        success = db.update_business(profile)
        if not success:
            raise HTTPException(status_code=500, detail="사업자 수정에 실패했습니다.")

        logger.info("사업자 수정 완료: %s", biz_id)
        return {"message": f"사업자 '{request.company_name}'이(가) 수정되었습니다."}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("사업자 수정 실패: %s", e)
        raise HTTPException(status_code=500, detail="서버 내부 오류가 발생했습니다")


@router.delete("/businesses/{biz_id}", summary="사업자 삭제")
async def delete_business(biz_id: str, db=Depends(get_db)):
    """사업자 프로필을 삭제합니다."""
    try:
        success = db.delete_business(biz_id)
        if not success:
            raise HTTPException(
                status_code=404,
                detail=f"사업자를 찾을 수 없습니다: {biz_id}",
            )

        logger.info("사업자 삭제 완료: %s", biz_id)
        return {"message": f"사업자 '{biz_id}'이(가) 삭제되었습니다."}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("사업자 삭제 실패: %s", e)
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
