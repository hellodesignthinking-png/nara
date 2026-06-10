"""
사업자 문서 파싱 모듈

사업자등록증, 재무제표 등의 문서에서 사업자 정보를 자동 추출합니다.

지원 방식:
  1. 정규식 기반 추출 (기본) — 외부 의존성 없음
  2. OpenAI Vision API (선택) — 이미지 파일도 처리 가능

추출 가능 정보:
  - 사업자등록번호, 상호(회사명), 대표자명
  - 업태, 종목(업종)
  - 사업장 소재지 → 지역
  - 연매출, 직원 수 (재무제표)
"""

import io
import json
import logging
import re
from pathlib import Path
from typing import Optional

from src.config import load_config

# Base64 인코딩 전 최대 이미지 크기 (5MB)
MAX_IMAGE_SIZE = 5 * 1024 * 1024

logger = logging.getLogger(__name__)


class BusinessDocParser:
    """
    사업자 관련 문서에서 정보를 자동 추출하는 파서

    사업자등록증(이미지/PDF)과 재무제표(PDF)를 파싱하여
    사업자 등록 폼에 필요한 필드를 자동 채워줍니다.
    """

    # 주요 지역 매핑 (주소 → 시/도)
    REGION_MAP = {
        '서울': '서울특별시', '부산': '부산광역시', '대구': '대구광역시',
        '인천': '인천광역시', '광주': '광주광역시', '대전': '대전광역시',
        '울산': '울산광역시', '세종': '세종특별자치시', '경기': '경기도',
        '강원': '강원특별자치도', '충북': '충청북도', '충남': '충청남도',
        '전북': '전북특별자치도', '전남': '전라남도', '경북': '경상북도',
        '경남': '경상남도', '제주': '제주특별자치도',
    }

    # 업태 → 나라장터 업종 매핑
    BUSINESS_TYPE_MAP = {
        '정보통신': ['IT/SW', 'SI', '정보시스템'],
        '소프트웨어': ['SW개발', 'SI', '소프트웨어'],
        '컨설팅': ['컨설팅', '경영자문'],
        '서비스': ['서비스업'],
        '광고': ['마케팅', '광고', '홍보'],
        '출판': ['출판', '인쇄'],
        '교육': ['교육', '연수'],
        '건설': ['건설', '토목', '시공'],
        '전기': ['전기', '설비'],
        '연구': ['연구개발', 'R&D', '기술개발'],
        '제조': ['제조업'],
        '도소매': ['유통', '도소매'],
    }

    def __init__(self, openai_api_key: str = '', gemini_api_key: str = '', engine: str = 'openai'):
        """
        Args:
            openai_api_key: OpenAI API 키 (Vision/LLM 분석 시 사용, 선택)
            gemini_api_key: Gemini API 키 (Vision/LLM 분석 시 사용, 선택)
            engine: 'openai' 또는 'gemini' (기본: 'openai')
        """
        self.engine = engine
        self.openai_api_key = openai_api_key
        self._config = load_config()
        self._openai_client = None
        self._gemini_client = None

        # Gemini 초기화
        if engine == 'gemini' and gemini_api_key:
            try:
                from google import genai
                self._gemini_client = genai.Client(api_key=gemini_api_key)
                logger.info("Gemini API 사용 가능 (문서 파싱)")
            except ImportError:
                logger.warning("google-genai 패키지 미설치 — 정규식 모드로 동작")

        # OpenAI 초기화 (Gemini가 없는 경우 폴백으로도 사용)
        if openai_api_key and not self._gemini_client:
            try:
                import openai
                self._openai_client = openai.OpenAI(api_key=openai_api_key)
                logger.info("OpenAI Vision API 사용 가능")
            except ImportError:
                logger.warning("openai 패키지 미설치 — 정규식 모드로 동작")


    # ══════════════════════════════════════════════
    # 메인 파싱 메서드
    # ══════════════════════════════════════════════

    def parse_business_doc(
        self,
        file_content: bytes,
        filename: str,
        doc_type: str = 'auto',
    ) -> dict:
        """
        사업자 문서를 파싱하여 구조화된 정보를 반환합니다.

        Args:
            file_content: 파일 바이너리 내용
            filename: 파일명 (확장자로 파일 형식 판별)
            doc_type: 문서 유형 ('registration'=사업자등록증, 'financial'=재무제표, 'auto'=자동)

        Returns:
            {
                'biz_id': '000-00-00000',
                'company_name': '회사명',
                'ceo_name': '대표자',
                'business_types': ['업종1', '업종2'],
                'regions': ['서울특별시'],
                'annual_revenue': 1000000000,
                'employee_count': 50,
                'keywords': ['키워드1', '키워드2'],
                'doc_type': 'registration',
                'confidence': 'high' | 'medium' | 'low',
                'raw_text': '추출된 원문 텍스트'
            }
        """
        ext = Path(filename).suffix.lower()
        result = {
            'biz_id': '',
            'company_name': '',
            'ceo_name': '',
            'business_types': [],
            'licenses': [],
            'regions': [],
            'annual_revenue': 0,
            'employee_count': 0,
            'keywords': [],
            'doc_type': doc_type,
            'confidence': 'low',
            'raw_text': '',
        }

        # 1단계: 텍스트 추출
        text = ''
        is_image = ext in ('.jpg', '.jpeg', '.png', '.bmp', '.gif', '.webp')

        if is_image and self._gemini_client:
            # 이미지 → Gemini Vision API
            return self._parse_with_gemini_vision(file_content, filename, doc_type)

        elif is_image and self._openai_client:
            # 이미지 → OpenAI Vision API
            return self._parse_with_vision(file_content, filename, doc_type)

        elif ext == '.pdf':
            text = self._extract_pdf_text(file_content)
            # PDF에서 텍스트가 추출되지 않으면 (스캔 PDF) OCR 또는 Vision 시도
            if not text.strip():
                # 1) OCR 시도 (pytesseract + pdfplumber 이미지 추출)
                ocr_text = self._ocr_pdf(file_content)
                if ocr_text.strip():
                    logger.info("PDF OCR 추출 성공 (%d글자)", len(ocr_text))
                    text = ocr_text
                # 2) OCR 실패 → Vision API 시도
                elif self._gemini_client:
                    logger.info("PDF 텍스트/OCR 추출 실패 — Gemini Vision API로 재시도")
                    return self._parse_with_gemini_vision(file_content, filename, doc_type)
                elif self._openai_client:
                    logger.info("PDF 텍스트/OCR 추출 실패 — OpenAI Vision API로 재시도")
                    return self._parse_with_vision(file_content, filename, doc_type)
        elif ext in ('.hwp', '.hwpx'):
            text = self._extract_hwp_text(file_content, filename)
        elif ext in ('.txt', '.csv'):
            text = self._decode_text(file_content)
        elif is_image:
            # 이미지인데 API 없음 → 명확한 에러 반환
            raise ValueError(
                "이미지 파일에서 정보를 추출하려면 AI API 키가 필요합니다. "
                "설정 → API 연결에서 Gemini 또는 OpenAI 키를 설정하거나, "
                "PDF 또는 텍스트 형식의 사업자등록증을 업로드해주세요."
            )
        else:
            text = self._decode_text(file_content)

        result['raw_text'] = text[:5000]  # 원문 제한

        if not text.strip():
            return result

        # 2단계: 문서 유형 자동 감지
        if doc_type == 'auto':
            if any(kw in text for kw in ['사업자등록증', '등록번호', '상호', '업태', '종목']):
                doc_type = 'registration'
            elif any(kw in text for kw in ['재무제표', '대차대조표', '손익계산서', '매출액', '당기순이익']):
                doc_type = 'financial'
            else:
                doc_type = 'registration'  # 기본값
            result['doc_type'] = doc_type

        # 3단계: LLM 파싱 (Gemini 우선, OpenAI 폴백)
        if self._gemini_client:
            return self._parse_with_gemini_llm(text, doc_type, result)
        if self._openai_client:
            return self._parse_with_llm(text, doc_type, result)

        # 4단계: 정규식 기반 파싱 (폴백)
        if doc_type == 'registration':
            self._parse_registration_regex(text, result)
        elif doc_type == 'financial':
            self._parse_financial_regex(text, result)

        return result

    # ══════════════════════════════════════════════
    # Gemini Vision API (이미지 직접 인식)
    # ══════════════════════════════════════════════

    def _parse_with_gemini_vision(self, file_content: bytes, filename: str, doc_type: str) -> dict:
        """Gemini Vision API로 이미지/PDF에서 사업자 정보를 추출합니다."""
        from google.genai import types

        ext = Path(filename).suffix.lower()
        mime_map = {
            '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png',
            '.gif': 'image/gif', '.webp': 'image/webp', '.bmp': 'image/bmp',
            '.pdf': 'application/pdf',
        }
        mime_type = mime_map.get(ext, 'image/jpeg')

        prompt = """이 이미지/문서는 한국의 사업자등록증 또는 재무제표입니다.
아래 JSON 형식으로 정보를 추출해주세요. 찾을 수 없는 항목은 빈 문자열로 남겨주세요.

{
  "biz_id": "사업자등록번호 (000-00-00000 형식)",
  "company_name": "상호(회사명)",
  "ceo_name": "대표자명",
  "business_types": ["업태에서 추출한 업종 목록"],
  "business_items": ["종목에서 추출한 세부 사업 목록"],
  "address": "사업장 소재지 전체 주소",
  "annual_revenue": 0,
  "employee_count": 0
}

JSON만 출력하세요."""

        try:
            response = self._gemini_client.models.generate_content(
                model="gemini-2.5-flash",
                contents=[
                    types.Content(
                        role="user",
                        parts=[
                            types.Part.from_text(text=prompt),
                            types.Part.from_bytes(data=file_content, mime_type=mime_type),
                        ],
                    ),
                ],
                config=types.GenerateContentConfig(
                    temperature=0.1,
                    max_output_tokens=1000,
                    response_mime_type="application/json",
                ),
            )

            data = json.loads(response.text)
            result = self._format_llm_result(data, 'high', doc_type)
            logger.info("Gemini Vision 파싱 완료: %s (confidence=%s)", filename, result['confidence'])
            return result

        except Exception as e:
            logger.error("Gemini Vision API 파싱 실패: %s", e)
            return {
                'biz_id': '', 'company_name': '', 'ceo_name': '',
                'business_types': [], 'licenses': [], 'regions': [],
                'annual_revenue': 0, 'employee_count': 0, 'keywords': [],
                'doc_type': doc_type, 'confidence': 'low',
                'raw_text': f'Gemini Vision API 오류: {str(e)}',
            }

    # ══════════════════════════════════════════════
    # Gemini LLM 텍스트 파싱
    # ══════════════════════════════════════════════

    def _parse_with_gemini_llm(self, text: str, doc_type: str, base_result: dict) -> dict:
        """Gemini LLM으로 텍스트에서 사업자 정보를 추출합니다."""
        from google.genai import types

        prompt = f"""아래 텍스트는 한국의 {'사업자등록증' if doc_type == 'registration' else '재무제표'}에서 추출한 내용입니다.
아래 JSON 형식으로 정보를 추출해주세요. 찾을 수 없는 항목은 빈 문자열이나 0으로 남겨주세요.

{{
  "biz_id": "사업자등록번호 (000-00-00000 형식)",
  "company_name": "상호(회사명)",
  "ceo_name": "대표자명",
  "business_types": ["업태/종목에서 추출한 업종 분류 목록"],
  "business_items": ["구체적인 사업 품목/서비스 목록"],
  "address": "사업장 소재지",
  "annual_revenue": "연매출액(숫자만, 원 단위)",
  "employee_count": "직원 수(숫자만)"
}}

추출 대상 텍스트:
---
{self._sanitize_for_prompt(text[:3000])}
---

JSON만 출력하세요."""

        try:
            response = self._gemini_client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.1,
                    max_output_tokens=800,
                    response_mime_type="application/json",
                ),
            )

            data = json.loads(response.text)
            result = self._format_llm_result(data, 'high', doc_type)
            result['raw_text'] = text[:3000]
            logger.info("Gemini LLM 파싱 완료 (confidence=%s)", result['confidence'])
            return result

        except Exception as e:
            logger.warning("Gemini LLM 파싱 실패, 정규식 폴백: %s", e)
            if doc_type == 'registration':
                self._parse_registration_regex(text, base_result)
            else:
                self._parse_financial_regex(text, base_result)
            return base_result

    # ══════════════════════════════════════════════
    # OpenAI Vision API (이미지 직접 인식)
    # ══════════════════════════════════════════════

    def _parse_with_vision(self, file_content: bytes, filename: str, doc_type: str) -> dict:
        """OpenAI Vision API로 이미지에서 사업자 정보를 추출합니다."""
        import base64

        ext = Path(filename).suffix.lower()
        mime_map = {'.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png',
                    '.gif': 'image/gif', '.webp': 'image/webp', '.bmp': 'image/bmp'}
        mime_type = mime_map.get(ext, 'image/jpeg')

        # 이미지 크기 제한 확인
        if len(file_content) > MAX_IMAGE_SIZE:
            logger.warning(
                "이미지 파일이 너무 큽니다: %d bytes (최대: %d bytes)",
                len(file_content), MAX_IMAGE_SIZE,
            )
            return {
                'biz_id': '', 'company_name': '', 'ceo_name': '',
                'business_types': [], 'licenses': [], 'regions': [],
                'annual_revenue': 0, 'employee_count': 0, 'keywords': [],
                'doc_type': doc_type, 'confidence': 'low',
                'raw_text': f'이미지 크기 초과: {len(file_content)} bytes',
            }

        b64_image = base64.b64encode(file_content).decode('utf-8')

        prompt = """이 이미지는 한국의 사업자등록증 또는 재무제표입니다.
아래 JSON 형식으로 정보를 추출해주세요. 찾을 수 없는 항목은 빈 문자열로 남겨주세요.

{
  "biz_id": "사업자등록번호 (000-00-00000 형식)",
  "company_name": "상호(회사명)",
  "ceo_name": "대표자명",
  "business_types": ["업태에서 추출한 업종 목록"],
  "business_items": ["종목에서 추출한 세부 사업 목록"],
  "address": "사업장 소재지 전체 주소",
  "annual_revenue": 0,
  "employee_count": 0
}

JSON만 출력하세요."""

        try:
            response = self._openai_client.chat.completions.create(
                model="gpt-4o",
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {
                            "url": f"data:{mime_type};base64,{b64_image}",
                            "detail": "high",
                        }},
                    ],
                }],
                max_tokens=1000,
                temperature=0.1,
            )

            raw = response.choices[0].message.content.strip()
            # JSON 블록 추출 (3단계 시도)
            data = None
            # 1단계: 전체 문자열을 직접 파싱 시도
            try:
                data = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                pass
            # 2단계: 첫 번째 '{' ~ 마지막 '}' 범위로 파싱 시도 (중첩 JSON 지원)
            if data is None:
                start = raw.find('{')
                end = raw.rfind('}')
                if start != -1 and end != -1 and end > start:
                    try:
                        data = json.loads(raw[start:end + 1])
                    except (json.JSONDecodeError, ValueError):
                        pass
            # 3단계: 단순 정규식 폴백 (중첩 없는 단순 JSON)
            if data is None:
                json_match = re.search(r'\{[^{}]*\}', raw, re.DOTALL)
                if json_match:
                    data = json.loads(json_match.group())
                else:
                    data = json.loads(raw)

            return self._format_llm_result(data, 'high', doc_type)

        except Exception as e:
            logger.error("Vision API 파싱 실패: %s", e)
            return {
                'biz_id': '', 'company_name': '', 'ceo_name': '',
                'business_types': [], 'licenses': [], 'regions': [],
                'annual_revenue': 0, 'employee_count': 0, 'keywords': [],
                'doc_type': doc_type, 'confidence': 'low',
                'raw_text': f'Vision API 오류: {str(e)}',
            }

    # ══════════════════════════════════════════════
    # OpenAI LLM 텍스트 파싱
    # ══════════════════════════════════════════════

    def _parse_with_llm(self, text: str, doc_type: str, base_result: dict) -> dict:
        """OpenAI LLM으로 텍스트에서 사업자 정보를 추출합니다."""
        prompt = f"""아래 텍스트는 한국의 {'사업자등록증' if doc_type == 'registration' else '재무제표'}에서 추출한 내용입니다.
아래 JSON 형식으로 정보를 추출해주세요. 찾을 수 없는 항목은 빈 문자열이나 0으로 남겨주세요.

{{
  "biz_id": "사업자등록번호 (000-00-00000 형식)",
  "company_name": "상호(회사명)",
  "ceo_name": "대표자명",
  "business_types": ["업태/종목에서 추출한 업종 분류 목록"],
  "business_items": ["구체적인 사업 품목/서비스 목록"],
  "address": "사업장 소재지",
  "annual_revenue": "연매출액(숫자만, 원 단위)",
  "employee_count": "직원 수(숫자만)"
}}

추출 대상 텍스트:
---
{self._sanitize_for_prompt(text[:3000])}
---

JSON만 출력하세요."""

        try:
            response = self._openai_client.chat.completions.create(
                model=self._config.openai_model,
                messages=[
                    {"role": "system", "content": "당신은 한국 사업자 문서에서 정보를 정확하게 추출하는 전문가입니다."},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=800,
                temperature=0.1,
                response_format={"type": "json_object"},
            )

            data = json.loads(response.choices[0].message.content)
            result = self._format_llm_result(data, 'high', doc_type)
            result['raw_text'] = text[:3000]
            return result

        except Exception as e:
            logger.warning("LLM 파싱 실패, 정규식 폴백: %s", e)
            if doc_type == 'registration':
                self._parse_registration_regex(text, base_result)
            else:
                self._parse_financial_regex(text, base_result)
            return base_result

    def _format_llm_result(self, data: dict, confidence: str, doc_type: str) -> dict:
        """LLM 추출 결과를 표준 형식으로 변환합니다."""
        # 업종 + 사업항목 병합
        biz_types = data.get('business_types', [])
        biz_items = data.get('business_items', [])
        all_types = list(set(biz_types + biz_items))

        # 주소에서 지역 추출
        regions = []
        address = data.get('address', '')
        if address:
            for short, full in self.REGION_MAP.items():
                if short in address:
                    regions.append(full)
                    break

        # 연매출 파싱
        revenue = data.get('annual_revenue', 0)
        if isinstance(revenue, str):
            revenue = int(re.sub(r'[^\d]', '', revenue) or '0')

        # 직원 수
        emp = data.get('employee_count', 0)
        if isinstance(emp, str):
            emp = int(re.sub(r'[^\d]', '', emp) or '0')

        # 키워드 자동 생성 (업종에서)
        keywords = []
        for t in all_types[:5]:
            for key, synonyms in self.BUSINESS_TYPE_MAP.items():
                if key in t or any(s in t for s in synonyms):
                    keywords.append(key)
                    break

        return {
            'biz_id': data.get('biz_id', ''),
            'company_name': data.get('company_name', ''),
            'ceo_name': data.get('ceo_name', ''),
            'business_types': all_types,
            'licenses': [],
            'regions': regions,
            'annual_revenue': revenue,
            'employee_count': emp,
            'keywords': list(set(keywords)),
            'doc_type': doc_type,
            'confidence': confidence,
            'raw_text': '',
        }

    # ══════════════════════════════════════════════
    # 입력 정제 / 인코딩 감지 헬퍼
    # ══════════════════════════════════════════════

    @staticmethod
    def _sanitize_for_prompt(text: str) -> str:
        """
        LLM 프롬프트에 삽입할 텍스트를 정제합니다.

        잠재적 프롬프트 인젝션 패턴을 제거하여
        LLM이 의도하지 않은 동작을 수행하는 것을 방지합니다.

        Args:
            text: 정제할 텍스트

        Returns:
            정제된 텍스트
        """
        if not text:
            return ""
        # 잠재적 인젝션 패턴 제거
        injection_patterns = [
            r'(?i)ignore\s+(previous|above|all)\s+instructions?',
            r'(?i)disregard\s+(previous|above|all)',
            r'(?i)you\s+are\s+now',
            r'(?i)new\s+instructions?:',
            r'(?i)system\s*:',
            r'(?i)assistant\s*:',
        ]
        sanitized = text
        for pattern in injection_patterns:
            sanitized = re.sub(pattern, '[FILTERED]', sanitized)
        return sanitized

    @staticmethod
    def _decode_text(file_content: bytes) -> str:
        """
        바이트 데이터를 텍스트로 디코딩합니다.

        UTF-8을 우선 시도하고, 실패 시 chardet로 인코딩을 감지합니다.

        Args:
            file_content: 디코딩할 바이트 데이터

        Returns:
            디코딩된 텍스트 문자열
        """
        try:
            return file_content.decode('utf-8')
        except UnicodeDecodeError:
            try:
                import chardet
                detected = chardet.detect(file_content)
                encoding = detected.get('encoding') or 'utf-8'
                return file_content.decode(encoding, errors='ignore')
            except Exception:
                return file_content.decode('utf-8', errors='ignore')

    # ══════════════════════════════════════════════
    # 정규식 기반 파싱 (폴백)
    # ══════════════════════════════════════════════

    def _parse_registration_regex(self, text: str, result: dict) -> None:
        """정규식으로 사업자등록증 정보를 추출합니다."""
        # 사업자등록번호
        biz_match = re.search(r'(\d{3})[- ]?(\d{2})[- ]?(\d{5})', text)
        if biz_match:
            result['biz_id'] = f"{biz_match.group(1)}-{biz_match.group(2)}-{biz_match.group(3)}"

        # 상호 (회사명)
        name_patterns = [
            r'상\s*호[:\s]*([^\n,]+)',
            r'법인명[:\s]*([^\n,]+)',
            r'회사명[:\s]*([^\n,]+)',
        ]
        for pat in name_patterns:
            m = re.search(pat, text)
            if m:
                result['company_name'] = m.group(1).strip()[:50]
                break

        # 대표자
        ceo_patterns = [
            r'대표자[:\s]*([^\n,]+)',
            r'성\s*명[:\s]*([^\n,]+)',
            r'대\s*표[:\s]*([^\n,]+)',
        ]
        for pat in ceo_patterns:
            m = re.search(pat, text)
            if m:
                result['ceo_name'] = m.group(1).strip()[:20]
                break

        # 업태
        type_patterns = [
            r'업\s*태[:\s]*([^\n]+)',
            r'업종[:\s]*([^\n]+)',
        ]
        for pat in type_patterns:
            m = re.search(pat, text)
            if m:
                raw = m.group(1).strip()
                types = [t.strip() for t in re.split(r'[,，/·]', raw) if t.strip()]
                result['business_types'].extend(types[:5])
                break

        # 종목
        item_patterns = [
            r'종\s*목[:\s]*([^\n]+)',
        ]
        for pat in item_patterns:
            m = re.search(pat, text)
            if m:
                raw = m.group(1).strip()
                items = [t.strip() for t in re.split(r'[,，/·]', raw) if t.strip()]
                result['business_types'].extend(items[:5])
                break

        # 중복 제거
        result['business_types'] = list(dict.fromkeys(result['business_types']))

        # 주소 → 지역
        addr_patterns = [
            r'소재지[:\s]*([^\n]+)',
            r'주\s*소[:\s]*([^\n]+)',
            r'사업장[:\s]*([^\n]+)',
        ]
        for pat in addr_patterns:
            m = re.search(pat, text)
            if m:
                addr = m.group(1).strip()
                for short, full in self.REGION_MAP.items():
                    if short in addr:
                        result['regions'] = [full]
                        break
                break

        # 키워드 자동 생성
        for t in result['business_types']:
            for key, synonyms in self.BUSINESS_TYPE_MAP.items():
                if key in t or any(s in t for s in synonyms):
                    result['keywords'].append(key)
        result['keywords'] = list(set(result['keywords']))

        # 신뢰도 결정
        filled = sum(1 for v in [result['biz_id'], result['company_name']] if v)
        result['confidence'] = 'high' if filled >= 2 else 'medium' if filled >= 1 else 'low'

    def _parse_financial_regex(self, text: str, result: dict) -> None:
        """정규식으로 재무제표 정보를 추출합니다."""
        # 매출액
        revenue_patterns = [
            r'매출액[:\s]*[\D]*([\d,]+)',
            r'매출[:\s]*[\D]*([\d,]+)',
            r'영업수익[:\s]*[\D]*([\d,]+)',
            r'수익[（(]?총[）)]?[:\s]*[\D]*([\d,]+)',
        ]
        for pat in revenue_patterns:
            m = re.search(pat, text)
            if m:
                raw = m.group(1).replace(',', '')
                if raw.isdigit():
                    result['annual_revenue'] = int(raw)
                    break

        # 직원 수
        emp_patterns = [
            r'종업원[:\s]*(\d+)',
            r'직원[수\s]*[:\s]*(\d+)',
            r'인원[:\s]*(\d+)',
            r'(\d+)\s*명',
        ]
        for pat in emp_patterns:
            m = re.search(pat, text)
            if m:
                result['employee_count'] = int(m.group(1))
                break

        # 회사명 (재무제표에서)
        name_patterns = [
            r'회사명[:\s]*([^\n,]+)',
            r'법인명[:\s]*([^\n,]+)',
            r'상호[:\s]*([^\n,]+)',
        ]
        for pat in name_patterns:
            m = re.search(pat, text)
            if m:
                result['company_name'] = m.group(1).strip()[:50]
                break

        result['confidence'] = 'medium' if result['annual_revenue'] else 'low'

    # ══════════════════════════════════════════════
    # 텍스트 추출 헬퍼
    # ══════════════════════════════════════════════

    def _extract_pdf_text(self, content: bytes) -> str:
        """PDF에서 텍스트를 추출합니다."""
        try:
            import pdfplumber
            with pdfplumber.open(io.BytesIO(content)) as pdf:
                pages_text = []
                for page in pdf.pages[:10]:  # 최대 10페이지
                    text = page.extract_text()
                    if text:
                        pages_text.append(text)
                return '\n'.join(pages_text)
        except Exception as e:
            logger.warning("PDF 텍스트 추출 실패: %s", e)
            return ''

    def _extract_hwp_text(self, content: bytes, filename: str) -> str:
        """HWP에서 텍스트를 추출합니다."""
        try:
            from src.parsers.hwp_parser import extract_text
            # 임시 파일로 저장 후 파싱
            import tempfile
            tmp_path = None
            try:
                with tempfile.NamedTemporaryFile(suffix=Path(filename).suffix, delete=False) as tmp:
                    tmp.write(content)
                    tmp_path = tmp.name
                text = extract_text(tmp_path)
                return text
            finally:
                if tmp_path:
                    Path(tmp_path).unlink(missing_ok=True)
        except Exception as e:
            logger.warning("HWP 텍스트 추출 실패: %s", e)
            return ''

    def _ocr_pdf(self, content: bytes) -> str:
        """
        스캔 PDF에서 pdfplumber 이미지 추출 → pytesseract OCR로 텍스트를 추출합니다.

        tesseract가 설치되지 않았으면 빈 문자열을 반환합니다.
        """
        try:
            import pytesseract
            from PIL import Image
        except ImportError:
            logger.debug("pytesseract/PIL 미설치 — OCR 건너뜀")
            return ''

        # tesseract 바이너리 존재 여부 확인
        try:
            pytesseract.get_tesseract_version()
        except Exception:
            logger.debug("tesseract 바이너리 미설치 — OCR 건너뜀")
            return ''

        try:
            import pdfplumber

            all_text = []
            with pdfplumber.open(io.BytesIO(content)) as pdf:
                for page_num, page in enumerate(pdf.pages[:5]):  # 최대 5페이지
                    # 1) 페이지에서 이미지 추출 시도
                    images = page.images
                    if images:
                        for img_info in images[:3]:  # 페이지당 최대 3개 이미지
                            try:
                                # pdfplumber 이미지에서 PIL Image 변환
                                x0 = img_info['x0']
                                y0 = img_info['top']
                                x1 = img_info['x1']
                                y1 = img_info['bottom']
                                cropped = page.crop((x0, y0, x1, y1)).to_image(resolution=300)
                                pil_image = cropped.original
                                ocr_result = pytesseract.image_to_string(pil_image, lang='kor+eng')
                                if ocr_result.strip():
                                    all_text.append(ocr_result.strip())
                            except Exception as img_err:
                                logger.debug("이미지 OCR 실패 (페이지 %d): %s", page_num + 1, img_err)
                                continue

                    # 2) 이미지가 없으면 페이지 전체를 이미지로 변환하여 OCR
                    if not all_text:
                        try:
                            page_image = page.to_image(resolution=300)
                            ocr_result = pytesseract.image_to_string(page_image.original, lang='kor+eng')
                            if ocr_result.strip():
                                all_text.append(ocr_result.strip())
                        except Exception as page_err:
                            logger.debug("페이지 전체 OCR 실패 (페이지 %d): %s", page_num + 1, page_err)

            return '\n'.join(all_text)

        except Exception as e:
            logger.warning("PDF OCR 처리 실패: %s", e)
            return ''
