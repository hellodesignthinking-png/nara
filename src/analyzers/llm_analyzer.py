"""
OpenAI API 기반 LLM 심층 분석 모듈

공고 정보와 RFP 문서를 AI로 분석하여 사업 요약, 핵심 요구사항,
필요 자격, 예산 적정성, 리스크 등을 도출합니다.

API 키 미설정 시에도 더미 결과를 반환하여 시스템이 중단되지 않습니다.
"""

import json
import logging
import re
import time


logger = logging.getLogger(__name__)

# RFP 텍스트 최대 길이 (토큰 제한 고려)
MAX_RFP_LENGTH_ANALYSIS = 6000
MAX_RFP_LENGTH_STRATEGY = 4000

# openai 라이브러리 선택적 임포트
try:
    import openai
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False
    logger.warning("openai 라이브러리가 설치되지 않았습니다. AI 분석이 비활성화됩니다.")

# google-generativeai 라이브러리 선택적 임포트
try:
    from google import genai
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False


class LLMAnalyzer:
    """
    OpenAI API를 활용한 공고 심층 분석 엔진

    GPT-4o 모델을 사용하여 입찰 공고를 분석하고,
    사업 요약·요구사항·리스크 등을 구조화된 JSON으로 반환합니다.

    API 키가 없거나 openai 라이브러리가 미설치된 경우
    자동으로 더미 결과를 반환하는 fallback 모드로 동작합니다.
    """

    def __init__(self, api_key: str = '', model: str = 'gpt-4o', engine: str = 'gemini'):
        """
        LLM 분석기를 초기화합니다.

        Args:
            api_key: API 키 (빈 문자열이면 fallback 모드)
            model: 사용할 모델명
            engine: 'openai' 또는 'gemini'
        """
        self.api_key = api_key
        self.model = model
        self.engine = engine
        self.client = None
        self.gemini_client = None
        self._fallback_mode = True
        self._total_tokens_used = 0

        if engine == 'gemini' and api_key and GEMINI_AVAILABLE:
            try:
                self.gemini_client = genai.Client(api_key=api_key)
                self._fallback_mode = False
                logger.info("Gemini 분석기 초기화 완료 (모델: %s)", model)
            except Exception as e:
                logger.warning("Gemini 클라이언트 초기화 실패: %s. Fallback 모드로 동작합니다.", e)
        elif engine == 'openai' and api_key and OPENAI_AVAILABLE:
            try:
                self.client = openai.OpenAI(
                    api_key=api_key,
                    max_retries=3,
                    timeout=60.0,
                )
                self._fallback_mode = False
                logger.info("OpenAI 분석기 초기화 완료 (모델: %s)", model)
            except Exception as e:
                logger.warning("OpenAI 클라이언트 초기화 실패: %s. Fallback 모드로 동작합니다.", e)
        else:
            if engine == 'gemini' and not GEMINI_AVAILABLE:
                logger.info("google-genai 라이브러리 미설치 → Fallback 모드")
            elif engine == 'openai' and not OPENAI_AVAILABLE:
                logger.info("openai 라이브러리 미설치 → Fallback 모드")
            elif not api_key:
                logger.info("API 키 미설정 → Fallback 모드")

    def __repr__(self) -> str:
        return f"LLMAnalyzer(engine={self.engine}, api_key=****)"

    @property
    def is_available(self) -> bool:
        """LLM 분석이 사용 가능한지 여부를 반환합니다."""
        return not self._fallback_mode

    @property
    def total_tokens_used(self) -> int:
        """API 호출에 사용된 총 토큰 수를 반환합니다."""
        return self._total_tokens_used

    @staticmethod
    def _sanitize_input(text: str) -> str:
        """
        사용자 입력에서 잠재적 프롬프트 인젝션 패턴을 제거합니다.

        'IGNORE', 'SYSTEM:', 'You are' 등으로 시작하는 줄을
        필터링하여 보안을 강화합니다.

        Args:
            text: 원본 텍스트

        Returns:
            정제된 텍스트
        """
        if not text:
            return text
        injection_patterns = [
            r'^\s*IGNORE\b',
            r'^\s*SYSTEM\s*:',
            r'^\s*You are\b',
            r'^\s*Forget\s+(all|previous|your)\b',
            r'^\s*Disregard\b',
            r'^\s*Override\b',
        ]
        lines = text.splitlines()
        filtered_lines = []
        for line in lines:
            is_injection = False
            for pattern in injection_patterns:
                if re.match(pattern, line, re.IGNORECASE):
                    is_injection = True
                    break
            if not is_injection:
                filtered_lines.append(line)
        return '\n'.join(filtered_lines)

    # ══════════════════════════════════════════════
    # 공개 API
    # ══════════════════════════════════════════════

    def analyze_bid(self, bid: dict, rfp_text: str = '') -> dict:
        """
        공고를 AI로 심층 분석합니다.

        분석 항목:
        - 사업 요약 (3줄)
        - 핵심 요구사항 목록
        - 필요 자격/실적 요건
        - 예산 적정성 평가
        - 주요 리스크

        Args:
            bid: 공고 정보 dict
            rfp_text: RFP(제안요청서) 본문 텍스트 (선택)

        Returns:
            {
                'summary': '사업 요약 (3줄)',
                'requirements': ['핵심 요구사항 1', ...],
                'qualifications': ['필요 자격/실적 1', ...],
                'budget_assessment': '예산 적정성 평가 내용',
                'risks': ['리스크 1', ...],
                'analysis_source': 'gpt-4o' | 'fallback',
            }
        """
        if self._fallback_mode:
            return self._generate_fallback_analysis(bid)

        # 프롬프트 구성 (사용자 입력 정제 적용)
        system_prompt = self._build_system_prompt()
        user_prompt = self._build_analysis_prompt(bid, self._sanitize_input(rfp_text))

        try:
            response = self._call_api(system_prompt, user_prompt)
            result = self._parse_analysis_response(response)
            result['analysis_source'] = self.model
            return result
        except Exception as e:
            logger.error("LLM 분석 실패: %s. Fallback 결과를 반환합니다.", e)
            return self._generate_fallback_analysis(bid)

    def analyze_with_context(
        self,
        bid: dict,
        rfp_text: str,
        past_awards: list[dict],
        news_articles: list[dict],
        business_profile: dict,
    ) -> dict:
        """
        과거 데이터와 뉴스를 종합한 컨텍스트 기반 심층 분석입니다.

        RAG 방식으로 수집된 모든 데이터를 프롬프트에 포함하여
        종합적이고 맥락을 반영한 분석 결과를 생성합니다.

        이 메서드는 strategy_engine에서 호출됩니다.

        Args:
            bid: 공고 정보 dict
            rfp_text: RFP 본문 텍스트
            past_awards: 과거 낙찰 이력 리스트
            news_articles: 관련 뉴스 기사 리스트
            business_profile: 사업자 프로필 dict

        Returns:
            {
                'bid_summary': '사업 핵심 방향 분석',
                'competitor_analysis': '경쟁사 분석',
                'differentiation_strategy': '차별화 전략',
                'risk_factors': '위험 요소',
                'budget_analysis': '예산 분석',
                'action_items': ['체크리스트 항목 1', ...],
                'overall_recommendation': '종합 권고',
                'analysis_source': 'gpt-4o' | 'fallback',
            }
        """
        if self._fallback_mode:
            return self._generate_fallback_strategy(bid, business_profile)

        system_prompt = self._build_strategy_system_prompt()
        user_prompt = self._build_strategy_prompt(
            bid, self._sanitize_input(rfp_text), past_awards, news_articles, business_profile
        )

        # 수집된 과거 데이터/뉴스가 없으면 Gemini Google Search 도구 활용
        use_grounding = (not past_awards and not news_articles)

        try:
            if use_grounding and self.engine == 'gemini' and self.gemini_client:
                response = self._call_gemini_with_search(
                    system_prompt, user_prompt, max_tokens=4000, temperature=0.3
                )
            else:
                response = self._call_api(system_prompt, user_prompt, max_tokens=4000)
            result = self._parse_strategy_response(response, bid=bid, business_profile=business_profile)
            result['analysis_source'] = self.model + (' +search' if use_grounding else '')
            return result
        except Exception as e:
            logger.error("LLM 컨텍스트 분석 실패: %s. Fallback 결과를 반환합니다.", e)
            return self._generate_fallback_strategy(bid, business_profile)

    # ══════════════════════════════════════════════
    # 프롬프트 빌더
    # ══════════════════════════════════════════════

    def _build_system_prompt(self) -> str:
        """기본 분석용 시스템 프롬프트를 생성합니다."""
        return """당신은 대한민국 나라장터(조달청) 입찰 공고 전문 분석가입니다.
공공조달 분야에서 20년 이상의 경험을 보유하고 있으며,
입찰 공고를 분석하여 핵심 정보를 정확하고 간결하게 요약합니다.

반드시 한국어로 답변하세요.
답변은 반드시 유효한 JSON 형식으로만 출력하세요. 설명이나 마크다운은 포함하지 마세요.

JSON 구조:
{
    "summary": "사업 요약 (3줄 이내, 줄바꿈은 \\n 사용)",
    "requirements": ["핵심 요구사항 1", "핵심 요구사항 2", ...],
    "qualifications": ["필요 자격/실적 1", ...],
    "budget_assessment": "예산 적정성 평가 (시장 대비 적정/과소/과다 등)",
    "risks": ["리스크 1", "리스크 2", ...]
}"""

    def _build_analysis_prompt(self, bid: dict, rfp_text: str = '') -> str:
        """공고 분석용 사용자 프롬프트를 구성합니다."""
        title = bid.get('title', bid.get('bidNtceNm', '제목 없음'))
        org = bid.get('organization', bid.get('ntceInsttNm', ''))
        budget = bid.get('budget', bid.get('presmptPrce', ''))
        deadline = bid.get('deadline', bid.get('bidClseDt', ''))
        category = bid.get('category', '')
        description = bid.get('description', '')

        prompt = f"""다음 나라장터 입찰 공고를 분석해 주세요.

■ 공고 기본 정보
- 공고명: {title}
- 발주기관: {org}
- 추정가격: {budget}
- 입찰마감: {deadline}
- 분류: {category}

■ 공고 상세 내용
{description or '(상세 내용 없음)'}
"""

        if rfp_text:
            # RFP가 너무 길면 앞부분만 사용 (토큰 제한 고려)
            max_rfp_length = MAX_RFP_LENGTH_ANALYSIS
            truncated_rfp = rfp_text[:max_rfp_length]
            if len(rfp_text) > max_rfp_length:
                truncated_rfp += "\n\n... (이하 생략) ..."

            prompt += f"""
■ RFP(제안요청서) 내용
{truncated_rfp}
"""

        prompt += """
위 공고를 분석하여 JSON 형식으로 답변해 주세요.
특히 다음에 주의하세요:
1. 사업의 핵심 목적과 방향을 3줄로 요약
2. 반드시 갖춰야 할 자격/실적 요건을 명확히 구분
3. 예산이 시장 가격 대비 적정한지 평가
4. 입찰 참여 시 주의해야 할 리스크 요인"""

        return prompt

    def _build_strategy_system_prompt(self) -> str:
        """전략 분석용 시스템 프롬프트를 생성합니다 (고도화 버전)."""
        return """당신은 대한민국 공공조달 입찰 전략 전문가이자, 나라장터(조달청) 협상계약 제안서 마스터입니다.
공공조달 분야 20년 이상의 경험을 보유하고 있으며, 수백 건의 낙찰을 이끌어낸 전략 수립 능력을 갖추고 있습니다.

## 핵심 분석 프레임워크: 나라장터 입찰 5대 성공 요인

1. **발주처의 올해 '숨은 의도' 파악**
   - RFP에 적혀있지 않지만, 해당 기관장의 올해 역점 사업/정책 방향을 파악
   - 뉴스 기사에서 기관의 최근 정책 기조를 분석
   - 제안서에 기관의 핵심 과제와 본 사업의 연계성을 녹여야 함

2. **독창적이고 실현 가능한 차별화 전략**
   - 작년 동일/유사 사업의 문제점을 분석하고 개선 방안 제시
   - 올해 RFP에서 새로 추가된 과업이 평가위원의 '핵심 감점/가점 요인'
   - 다른 지자체에서 먼저 진행된 동일 성격 사업의 우수 사례 벤치마킹

3. **정량적 리스크 방어**
   - 유사 사업 실적, 참여 인력 등급 등 감점 요인 철저히 배제
   - 과거 낙찰 데이터 기반 적정 투찰률 제안
   - 필수 인증/자격 체크리스트 완비

4. **과거 사업 KPI 기반 차별화 (핵심!)**
   - 작년 동일/유사 사업의 수행사가 누구인지, 그 결과가 어떠했는지 반드시 분석
   - 작년 수행사의 강점과 약점을 구체적으로 파악하여 올해 제안에 반영
   - 성과지표(KPI) 기반으로 "작년 대비 xx% 향상" 등 정량적 차별화 포인트 제시
   - 작년 사업의 미흡했던 부분을 올해 어떻게 보완할 것인지 구체적 방안 제시

5. **뉴스·트렌드 기반 시의성 확보**
   - 발주기관의 최근 뉴스, 정책 발표, 기관장 발언을 분석
   - 올해 해당 분야의 트렌드(AI, 디지털전환, ESG 등)를 제안서에 반영
   - 국정과제, 지자체 역점사업과의 연계 포인트 도출

반드시 한국어로 답변하세요.
답변은 반드시 유효한 JSON 형식으로만 출력하세요.

JSON 구조:
{
    "bid_summary": "사업 핵심 방향 분석 + 발주처의 숨은 의도 해석 (5줄 이내)",
    "org_policy_insight": "발주처(기관장)의 올해 정책 방향 및 연계 전략",
    "past_project_analysis": "작년 수행사 분석 (수행사명, 수행 결과, KPI, 강점/약점)",
    "year_over_year_improvement": "올해 차별화 포인트 (작년 대비 개선점, 정량적 KPI 목표)",
    "competitor_analysis": "경쟁사 분석 (과거 수주업체, 투찰 패턴, 예상 경쟁사)",
    "differentiation_strategy": "차별화 전략 (작년 대비 개선점, 우수 사례 벤치마킹, 구체적 실행방안)",
    "risk_factors": "리스크 요소 (자격 제한, 지역 제한, 감점 요인)",
    "budget_analysis": "예산 분석 (전년 대비 변화, 적정 투찰률 제안)",
    "action_items": ["입찰 준비 체크리스트 항목 1", "항목 2", ...],
    "proposal_outline": "제안서 기획 뼈대 (배경/목적 → 차별화 포인트 → 기술 방법론 → 추진 체계)",
    "overall_recommendation": "종합 권고 (참여 여부, 핵심 전략 3줄 요약)",
    "scorecard_feedback": "적격심사 시뮬레이션 결과(정량 평가 점수 부족 요인 등)에 대한 구체적 AI 피드백 및 대응 전략",
    "win_themes": [
        {"theme": "핵심 가치 제안 테마 제목 1", "description": "해당 테마의 상세 설명 및 제안 논거"},
        {"theme": "핵심 가치 제안 테마 제목 2", "description": "해당 테마의 상세 설명 및 제안 논거"}
    ],
    "compliance_matrix": [
        {"requirement": "RFP 요구사항 항목 1", "importance": "필수/우선", "proposal_response": "해당 요구사항을 만족시키기 위한 구체적 제안 기술/방법론"}
    ]
}"""

    def _build_strategy_prompt(
        self,
        bid: dict,
        rfp_text: str,
        past_awards: list[dict],
        news_articles: list[dict],
        business_profile: dict,
    ) -> str:
        """전략 분석용 사용자 프롬프트를 구성합니다 (RAG 방식)."""
        title = bid.get('title', bid.get('bidNtceNm', '제목 없음'))
        org = bid.get('organization', bid.get('ntceInsttNm', ''))
        budget = bid.get('budget', bid.get('presmptPrce', ''))
        deadline = bid.get('deadline', bid.get('bidClseDt', ''))

        prompt = f"""다음 입찰 공고에 대한 종합 전략 분석을 수행해 주세요.

═══════════════════════════════════════
▶ 1. 공고 기본 정보
═══════════════════════════════════════
- 공고명: {title}
- 발주기관: {org}
- 추정가격: {budget}
- 입찰마감: {deadline}
"""

        # RFP 내용 추가
        if rfp_text:
            max_len = MAX_RFP_LENGTH_STRATEGY
            truncated = rfp_text[:max_len]
            if len(rfp_text) > max_len:
                truncated += "\n... (이하 생략) ..."
            prompt += f"""
═══════════════════════════════════════
▶ 2. RFP(제안요청서) 내용
═══════════════════════════════════════
{truncated}
"""

        # 과거 낙찰 이력
        if past_awards:
            prompt += """
═══════════════════════════════════════
▶ 3. 과거 유사 사업 낙찰 이력
═══════════════════════════════════════
"""
            for i, award in enumerate(past_awards[:10], 1):  # 최대 10건
                award_name = award.get('name', award.get('bidNtceNm', ''))
                award_org = award.get('organization', award.get('dminsttNm', ''))
                award_winner = award.get('winner', award.get('opengRsltCmpnm', ''))
                award_amount = award.get('amount', award.get('sucsfbidAmt', ''))
                award_date = award.get('date', award.get('opengDt', ''))
                prompt += f"  {i}. [{award_date}] {award_name}\n"
                prompt += f"     - 발주기관: {award_org}\n"
                prompt += f"     - 낙찰업체: {award_winner}\n"
                prompt += f"     - 낙찰금액: {award_amount}\n"

        # 뉴스 기사
        if news_articles:
            prompt += """
═══════════════════════════════════════
▶ 4. 관련 뉴스 기사
═══════════════════════════════════════
"""
            for i, article in enumerate(news_articles[:5], 1):  # 최대 5건
                art_title = article.get('title', '')
                art_desc = article.get('description', '')
                art_date = article.get('date', article.get('pubDate', ''))
                prompt += f"  {i}. [{art_date}] {art_title}\n"
                if art_desc:
                    prompt += f"     {art_desc[:200]}\n"

        # 사업자 프로필
        if business_profile:
            biz_name = business_profile.get('name', '')
            biz_types = ', '.join(business_profile.get('business_types', []))
            biz_licenses = ', '.join(business_profile.get('licenses', []))
            biz_region = business_profile.get('region', '')
            past_projects = business_profile.get('past_projects', [])

            prompt += f"""
═══════════════════════════════════════
▶ 5. 참여 검토 사업자 정보
═══════════════════════════════════════
- 업체명: {biz_name}
- 업종: {biz_types}
- 보유 면허: {biz_licenses}
- 소재지: {biz_region}
- 주요 실적:
"""
            for proj in past_projects[:5]:
                proj_name = proj.get('name', '')
                proj_year = proj.get('year', '')
                # proj_amount가 빈 문자열이나 잘못된 값일 수 있으므로 안전하게 변환
                try:
                    proj_amount = int(proj.get('amount', 0) or 0)
                except (ValueError, TypeError):
                    proj_amount = 0
                prompt += f"  · {proj_name} ({proj_year}년, {proj_amount:,}만원)\n"

        prompt += """
═══════════════════════════════════════

위 모든 정보를 종합하여 입찰 전략을 JSON 형식으로 분석해 주세요.

## 반드시 포함할 분석 관점 (나라장터 입찰 3대 성공 요인):

### 1. 발주처의 숨은 의도 파악
- 뉴스 기사에서 발주기관의 올해 정책 방향/역점 사업을 파악하세요
- 제안서에 어떤 키워드를 녹여야 평가위원의 가산점을 받을 수 있는지 구체적으로 제시

### 2. 작년 대비 차별화 전략
- 과거 낙찰 이력의 수주업체가 사용했을 방식을 분석하고, 이를 넘어서는 전략 제시
- 올해 공고에서 신규/변경된 요구사항이 있다면 이것이 핵심 평가 포인트

### 3. 정량적 리스크 방어
- 과거 낙찰 데이터를 기반으로 적정 투찰률(%) 범위를 구체적으로 제안
- 필수 자격/면허/실적 요건을 체크리스트로 정리
- 감점 요인이 될 수 있는 항목을 빠짐없이 나열

### 4. 제안서 기획 뼈대 (proposal_outline)
다음 구조로 제안서 초안 뼈대를 작성해 주세요:
  1) 배경 및 목적 (발주처 맞춤형 — 기관의 정책 방향과 사업 연계성 기술)
  2) 작년 사업 분석 및 차별화 포인트
  3) 기술 방법론 및 추진 전략
  4) 경쟁 우위 및 투찰 전략
"""
        return prompt

    # ══════════════════════════════════════════════
    # API 호출 및 응답 파싱
    # ══════════════════════════════════════════════

    def _call_api(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 2500,
        temperature: float = 0.3,
    ) -> str:
        """
        OpenAI API를 호출하고 응답 텍스트를 반환합니다.

        Args:
            system_prompt: 시스템 프롬프트
            user_prompt: 사용자 프롬프트
            max_tokens: 최대 출력 토큰 수
            temperature: 생성 온도 (낮을수록 일관성 높음)

        Returns:
            AI 응답 텍스트
        """
        if self.engine == 'gemini' and self.gemini_client:
            return self._call_gemini(system_prompt, user_prompt, max_tokens, temperature)

        # OpenAI 클라이언트가 초기화되지 않은 경우 방어 (Gemini 초기화 실패 등)
        if self.client is None:
            raise RuntimeError(
                f"LLM 클라이언트가 초기화되지 않았습니다 (engine={self.engine}). "
                "API 키와 라이브러리 설치 상태를 확인하세요."
            )

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=max_tokens,
            temperature=temperature,
            response_format={"type": "json_object"},
        )

        if not response.choices or not response.choices[0].message:
            raise RuntimeError('LLM API 응답이 비어있습니다')
        content = response.choices[0].message.content or ''
        if not content:
            raise RuntimeError('LLM API 응답 content가 비어있습니다')
        if response.usage:
            self._total_tokens_used += response.usage.total_tokens
            logger.debug("OpenAI API 응답 토큰: %s", response.usage.total_tokens)
        return content

    def _call_gemini(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 2500,
        temperature: float = 0.3,
    ) -> str:
        """
        Google Gemini API를 호출하고 응답 텍스트를 반환합니다.
        """
        from google.genai import types

        full_prompt = f"{system_prompt}\n\n{user_prompt}\n\n위 내용을 분석하여 JSON 형식으로 답변해주세요."

        # 재시도 로직 (지수 백오프)
        max_retries = 3
        last_error = None
        for attempt in range(max_retries):
            try:
                response = self.gemini_client.models.generate_content(
                    model=self.model,
                    contents=full_prompt,
                    config=types.GenerateContentConfig(
                        temperature=temperature,
                        max_output_tokens=max_tokens,
                        response_mime_type="application/json",
                    ),
                )

                content = response.text
                self._total_tokens_used += len(full_prompt) // 4 + len(content) // 4  # 추정 토큰 수
                logger.debug("Gemini API 응답 받음")
                return content
            except Exception as e:
                last_error = e
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt
                    logger.warning(
                        "Gemini API 호출 실패 (시도 %d/%d): %s. %d초 후 재시도...",
                        attempt + 1, max_retries, e, wait_time
                    )
                    time.sleep(wait_time)
                else:
                    logger.error("Gemini API 호출 최종 실패: %s", e)
        raise last_error

    def _call_gemini_with_search(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 4000,
        temperature: float = 0.3,
    ) -> str:
        """
        Google Gemini API를 Google Search 도구와 함께 호출합니다.

        과거 수행사, 뉴스, KPI 정보를 실시간 웹 검색으로 수집하여
        전략 보고서의 품질을 크게 향상시킵니다.
        """
        from google.genai import types

        # Google Search 도구 설정
        google_search_tool = types.Tool(
            google_search=types.GoogleSearch()
        )

        full_prompt = f"""{system_prompt}

{user_prompt}

## 추가 지시사항 (Google Search 활용)
위 공고에 대해 다음 정보를 웹에서 검색하여 분석에 반영해주세요:
1. 작년 동일/유사 사업의 수행사(낙찰업체)가 누구였는지
2. 작년 사업의 결과와 성과지표(KPI)
3. 발주기관의 최근 정책 방향, 기관장 발언
4. 해당 분야의 최신 트렌드와 우수 사례

검색 결과를 바탕으로 JSON 형식으로 답변해주세요."""

        try:
            response = self.gemini_client.models.generate_content(
                model=self.model,
                contents=full_prompt,
                config=types.GenerateContentConfig(
                    temperature=temperature,
                    max_output_tokens=max_tokens,
                    tools=[google_search_tool],
                    # tools와 response_mime_type 동시 사용 불가 → 수동 JSON 추출
                ),
            )

            content = response.text or ''
            # JSON 블록 추출 (```json ... ``` 형태로 올 수 있음)

            json_match = re.search(r'```json\s*(.*?)\s*```', content, re.DOTALL)
            if json_match:
                content = json_match.group(1)
            else:
                # { 로 시작하는 JSON 찾기 (중첩된 괄호 지원)
                brace_start = content.find('{')
                if brace_start != -1:
                    depth = 0
                    brace_end = brace_start
                    for i in range(brace_start, len(content)):
                        if content[i] == '{':
                            depth += 1
                        elif content[i] == '}':
                            depth -= 1
                            if depth == 0:
                                brace_end = i
                                break
                    content = content[brace_start:brace_end + 1]

            logger.info("Gemini + Google Search 응답 받음 (grounding 활용)")
            return content

        except Exception as e:
            # Google Search가 실패하면 일반 Gemini API로 폴백
            logger.warning("Gemini Search 실패, 일반 모드로 폴백: %s", e)
            return self._call_gemini(system_prompt, user_prompt, max_tokens, temperature)

    def _parse_analysis_response(self, response_text: str) -> dict:
        """분석 API 응답을 파싱합니다."""
        try:
            data = json.loads(response_text)
            return {
                'summary': data.get('summary', '분석 요약을 생성할 수 없습니다.'),
                'requirements': data.get('requirements', []),
                'qualifications': data.get('qualifications', []),
                'budget_assessment': data.get('budget_assessment', '예산 정보가 부족합니다.'),
                'risks': data.get('risks', []),
            }
        except json.JSONDecodeError:
            logger.warning("API 응답 JSON 파싱 실패. 원본 텍스트를 summary에 포함합니다.")
            return {
                'summary': response_text[:500],
                'requirements': [],
                'qualifications': [],
                'budget_assessment': '파싱 실패',
                'risks': ['API 응답을 정상적으로 파싱하지 못했습니다.'],
            }

    def _parse_strategy_response(self, response_text: str, bid=None, business_profile=None) -> dict:
        """전략 분석 API 응답을 파싱합니다."""
        try:
            data = json.loads(response_text)
            return {
                'bid_summary': data.get('bid_summary', ''),
                'org_policy_insight': data.get('org_policy_insight', ''),
                'past_project_analysis': data.get('past_project_analysis', ''),
                'year_over_year_improvement': data.get('year_over_year_improvement', ''),
                'competitor_analysis': data.get('competitor_analysis', ''),
                'differentiation_strategy': data.get('differentiation_strategy', ''),
                'risk_factors': data.get('risk_factors', ''),
                'budget_analysis': data.get('budget_analysis', ''),
                'action_items': data.get('action_items', []),
                'proposal_outline': data.get('proposal_outline', ''),
                'overall_recommendation': data.get('overall_recommendation', ''),
                'scorecard_feedback': data.get('scorecard_feedback', ''),
                'win_themes': data.get('win_themes', []),
                'compliance_matrix': data.get('compliance_matrix', []),
            }
        except json.JSONDecodeError:
            logger.warning("전략 분석 JSON 파싱 실패.")
            return self._generate_fallback_strategy(bid or {}, business_profile or {})

    # ══════════════════════════════════════════════
    # Fallback (API 키 미설정 안내)
    # ══════════════════════════════════════════════

    def _generate_fallback_analysis(self, bid: dict) -> dict:
        """
        API 사용 불가 시 기본 분석 결과를 생성합니다.

        공고 정보에서 추출 가능한 정보를 최대한 활용하여
        구조화된 결과를 반환합니다.
        """
        title = bid.get('title', bid.get('bidNtceNm', '제목 없음'))
        org = bid.get('organization', bid.get('ntceInsttNm', ''))
        budget = bid.get('budget', bid.get('presmptPrce', ''))
        deadline = bid.get('deadline', bid.get('bidClseDt', ''))

        summary_lines = [
            "⚠️ AI 분석 API 키(OpenAI 또는 Gemini)가 설정되지 않았습니다.",
            "설정 페이지에서 API 키를 입력해 주세요.",
            f"본 사업은 {org}에서 발주한 '{title}'입니다." if org else f"'{title}' 사업입니다.",
            f"추정가격: {budget}, 마감일: {deadline}" if budget or deadline else "",
        ]

        return {
            'summary': '\n'.join(line for line in summary_lines if line),
            'requirements': [
                '⚠️ AI 분석이 비활성화 상태입니다. 공고 원문을 직접 확인하세요.',
            ],
            'qualifications': [
                '⚠️ AI 분석이 비활성화 상태입니다. 참가 자격 조건을 공고 원문에서 확인하세요.',
            ],
            'budget_assessment': f'추정가격 {budget} — AI 분석 활성화 시 상세 평가가 제공됩니다.',
            'risks': [
                'AI 분석이 비활성화되어 자동 리스크 분석이 불가합니다.',
            ],
            'analysis_source': 'fallback',
        }

    def _generate_fallback_strategy(self, bid: dict, business_profile: dict) -> dict:
        """API 사용 불가 시 기본 전략 결과를 생성합니다."""
        title = bid.get('title', bid.get('bidNtceNm', '정보 없음'))
        biz_name = business_profile.get('name', '미지정')

        return {
            'bid_summary': f"'{title}' 사업에 대한 분석입니다. AI 분석 활성화 시 상세 요약이 제공됩니다.",
            'competitor_analysis': '과거 낙찰 데이터를 기반으로 한 경쟁사 분석은 AI 활성화 시 제공됩니다.',
            'differentiation_strategy': f"'{biz_name}'의 강점을 바탕으로 한 차별화 전략은 AI 활성화 시 제공됩니다.",
            'risk_factors': '공고 원문을 직접 확인하여 자격 제한, 지역 제한 등을 검토하세요.',
            'budget_analysis': '예산 추이 분석은 AI 활성화 시 제공됩니다.',
            'action_items': [
                '공고 원문 및 첨부파일 다운로드',
                '제안요청서(RFP) 상세 검토',
                '참가 자격 요건 확인',
                '필수 면허/자격 보유 여부 확인',
                '유사 사업 실적 증빙 자료 준비',
                '제안서 작성 일정 수립',
                '현장설명회 참석 여부 확인',
            ],
            'overall_recommendation': '⚠️ AI 분석 API 키(OpenAI 또는 Gemini)가 설정되지 않았습니다. 설정 페이지에서 API 키를 입력해 주세요.',
            'scorecard_feedback': '정량 평가 시뮬레이션 피드백은 AI 활성화 시 제공됩니다.',
            'win_themes': [],
            'compliance_matrix': [],
            'analysis_source': 'fallback',
        }

    # ══════════════════════════════════════════════
    # 강화된 전략 분석 (구조화 분석 데이터 통합)
    # ══════════════════════════════════════════════

    def generate_enhanced_strategy(self, bid: dict, business_profile: dict,
                                    structured_analysis: dict) -> dict:
        """
        구조화된 분석 결과를 포함한 강화된 전략 보고서를 생성합니다.

        경쟁사 수주 패턴, 발주기관 정책 방향, 지역/도시 트렌드,
        투찰률 최적화, RFP 전년 대비 변화점 데이터를 LLM 프롬프트에
        통합하여 기존 전략 보고서 대비 훨씬 정밀한 결과를 생성합니다.

        Args:
            bid: 공고 정보 dict
            business_profile: 사업자 프로필 dict
            structured_analysis: 사전 분석 결과 dict
                - competitor_data: 경쟁사 수주 패턴 분석 결과
                - org_policy: 발주기관 정책 방향 분석 결과
                - regional_trend: 지역/도시 트렌드 분석 결과
                - bid_rate_optimization: 투찰률 최적화 분석 결과
                - rfp_changes: RFP 전년 대비 변화점
                - past_awards: 과거 낙찰 이력 리스트

        Returns:
            강화된 전략 보고서 dict (bid_summary, competitor_analysis,
            differentiation_strategy 등 포함)
        """
        if self._fallback_mode:
            return self._generate_fallback_strategy(bid, business_profile)

        # ── 시스템 프롬프트 구성 (기존 전략 프롬프트 + 추가 분석 데이터 지침) ──
        base_system_prompt = self._build_strategy_system_prompt()

        enhanced_system_prompt = base_system_prompt + """

## 추가 분석 데이터 활용 지침

이번 분석에는 아래 6가지 사전 분석 결과가 함께 제공됩니다.
반드시 이 데이터를 전략 수립에 반영하세요:

1. **경쟁사 수주 패턴 데이터**: 과거 낙찰 이력에서 도출된 주요 경쟁사 목록,
   수주 빈도, 평균 투찰률, 강점/약점을 분석에 활용하세요.

2. **발주기관 정책 방향 데이터**: 해당 기관의 최근 정책 기조, 역점 사업,
   기관장 방향성을 제안서의 배경/목적에 연계하세요.

3. **지역/도시 트렌드 데이터**: 해당 지역의 산업 트렌드, 예산 규모 변화,
   주요 발주 카테고리를 분석에 반영하세요.

4. **투찰률 최적화 분석**: 과거 낙찰 데이터 기반 통계적 최적 투찰률과
   범위를 예산 분석에 반드시 반영하세요.

5. **RFP 전년 대비 변화점**: 전년도 동일/유사 사업 대비 올해 RFP에서
   추가/삭제/변경된 요구사항이 핵심 평가 포인트입니다.
   이 변화점을 차별화 전략의 중심에 두세요.

6. **적격심사 및 정량평가 시뮬레이션**: 정량평가 예상 배점과 안정권 여부,
   점수 부족 시 제안하는 공동수급(컨소시엄) 등의 극복 전략이 제공됩니다.
   이 정량적 리스크 및 보완 방안을 분석에 명확히 반영하세요."""

        # ── 사용자 프롬프트 구성 ──
        user_prompt = self._build_enhanced_user_prompt(
            bid, business_profile, structured_analysis
        )

        try:
            response = self._call_api(
                enhanced_system_prompt, user_prompt,
                max_tokens=5000, temperature=0.3,
            )
            result = self._parse_strategy_response(
                response, bid=bid, business_profile=business_profile
            )
            result['analysis_source'] = self.model + ' (enhanced)'
            return result

        except Exception as e:
            logger.error("강화 전략 분석 LLM 호출 실패: %s. 폴백 결과를 반환합니다.", e)
            return self._generate_fallback_strategy(bid, business_profile)

    def _build_enhanced_user_prompt(
        self,
        bid: dict,
        business_profile: dict,
        structured_analysis: dict,
    ) -> str:
        """
        강화된 전략 분석용 사용자 프롬프트를 구성합니다.

        기존 공고/사업자 정보에 5가지 구조화된 분석 데이터를
        읽기 쉬운 섹션 형태로 추가합니다.

        Args:
            bid: 공고 정보 dict
            business_profile: 사업자 프로필 dict
            structured_analysis: 사전 분석 결과 dict

        Returns:
            사용자 프롬프트 문자열
        """
        title = bid.get('title', bid.get('bidNtceNm', '제목 없음'))
        org = bid.get('org_name', bid.get('ntceInsttNm', bid.get('organization', '')))
        budget = bid.get('budget', bid.get('presmptPrce', ''))
        deadline = bid.get('bid_close_dt', bid.get('bidClseDt', bid.get('deadline', '')))
        rfp_text = self._sanitize_input(bid.get('rfp_text', '') or '')

        prompt = f"""다음 입찰 공고에 대한 고도화 전략 분석을 수행해 주세요.
아래에 5가지 사전 분석 데이터가 함께 제공됩니다.

═══════════════════════════════════════
▶ 1. 공고 기본 정보
═══════════════════════════════════════
- 공고명: {title}
- 발주기관: {org}
- 추정가격: {budget}
- 입찰마감: {deadline}
- 분류: {bid.get('category', '')}
- 지역: {bid.get('region', '')}
- 계약방법: {bid.get('contract_method', '')}
"""

        # RFP 내용
        if rfp_text:
            max_len = MAX_RFP_LENGTH_STRATEGY
            truncated = rfp_text[:max_len]
            if len(rfp_text) > max_len:
                truncated += "\n... (이하 생략) ..."
            prompt += f"""
═══════════════════════════════════════
▶ 2. RFP(제안요청서) 내용
═══════════════════════════════════════
{truncated}
"""

        # 사업자 프로필
        if business_profile:
            biz_name = business_profile.get('company_name', business_profile.get('name', ''))
            biz_types = business_profile.get('business_types', '[]')
            biz_licenses = business_profile.get('licenses', '[]')
            biz_regions = business_profile.get('regions', business_profile.get('region', ''))

            prompt += f"""
═══════════════════════════════════════
▶ 3. 참여 검토 사업자 정보
═══════════════════════════════════════
- 업체명: {biz_name}
- 업종: {biz_types}
- 보유 면허: {biz_licenses}
- 소재지: {biz_regions}
"""

        # ── 구조화된 분석 데이터 추가 ──

        # 경쟁사 수주 패턴 데이터
        competitor_data = structured_analysis.get('competitor_data', {})
        competitors = competitor_data.get('top_competitors', competitor_data.get('competitors', []))
        prompt += """
═══════════════════════════════════════
▶ 4. 경쟁사 수주 패턴 분석 데이터
═══════════════════════════════════════
"""
        if competitors:
            for i, comp in enumerate(competitors[:10], 1):
                name = comp.get('name', comp.get('winner_name', ''))
                count = comp.get('win_count', comp.get('award_count', 0))
                avg_rate = comp.get('avg_bid_rate', comp.get('avg_rate', ''))
                prompt += f"  {i}. {name}: 수주 {count}건"
                if avg_rate:
                    prompt += f", 평균 투찰률 {avg_rate}%"
                prompt += "\n"
        else:
            prompt += "  (경쟁사 수주 데이터 없음)\n"

        # 발주기관 정책 방향 데이터
        org_policy = structured_analysis.get('org_policy', {})
        prompt += """
═══════════════════════════════════════
▶ 5. 발주기관 정책 방향 분석 데이터
═══════════════════════════════════════
"""
        if org_policy and not org_policy.get('error'):
            org_name = org_policy.get('org_name', '')
            total_bids = org_policy.get('total_bids', 0)
            total_awards = org_policy.get('total_awards', 0)
            if org_name:
                prompt += f"  기관명: {org_name}\n"
            if total_bids:
                prompt += f"  총 공고 건수: {total_bids}건, 총 낙찰 건수: {total_awards}건\n"
            top_categories = org_policy.get('top_categories', [])
            if top_categories:
                cat_str = ', '.join(f"{c['category']}({c['count']}건)" for c in top_categories[:5])
                prompt += f"  주력 분야: {cat_str}\n"
            preferred_vendors = org_policy.get('preferred_vendors', [])
            if preferred_vendors:
                vendor_str = ', '.join(f"{v['name']}({v['win_count']}건)" for v in preferred_vendors[:5])
                prompt += f"  선호 업체: {vendor_str}\n"
            award_stats = org_policy.get('award_stats', {})
            if award_stats.get('avg_bid_rate'):
                prompt += f"  평균 투찰률: {award_stats['avg_bid_rate']}%\n"
            bid_chars = org_policy.get('bid_characteristics', {})
            if bid_chars.get('common_bid_methods'):
                methods = ', '.join(m['method'] for m in bid_chars['common_bid_methods'][:3])
                prompt += f"  주요 입찰방식: {methods}\n"
        else:
            prompt += "  (발주기관 정책 데이터 없음)\n"

        # 지역/도시 트렌드 데이터
        regional_trend = structured_analysis.get('regional_trend', {})
        prompt += """
═══════════════════════════════════════
▶ 6. 지역/도시 트렌드 분석 데이터
═══════════════════════════════════════
"""
        if regional_trend and not regional_trend.get('error'):
            region_name = regional_trend.get('region', '')
            market = regional_trend.get('market_overview', {})
            if region_name:
                prompt += f"  지역: {region_name}\n"
            if market.get('total_awards'):
                prompt += f"  총 낙찰 건수: {market['total_awards']}건\n"
                prompt += f"  총 낙찰 금액: {market.get('total_budget', 0):,}원\n"
                prompt += f"  평균 낙찰 금액: {market.get('avg_award_amount', 0):,}원\n"
            sector_analysis = regional_trend.get('sector_analysis', [])
            if sector_analysis:
                sector_str = ', '.join(
                    f"{s['sector']}({s['bid_count']}건)" for s in sector_analysis[:5]
                )
                prompt += f"  주요 발주 분야: {sector_str}\n"
                for s in sector_analysis[:3]:
                    if s.get('top_winners'):
                        prompt += f"    {s['sector']} 상위 수주사: {', '.join(s['top_winners'])}\n"
            local_pref = regional_trend.get('local_preference', {})
            if local_pref.get('recommendation'):
                prompt += f"  지역 업체 우대: {local_pref['recommendation']}\n"
            pa = regional_trend.get('policy_alignment', {})
            if pa.get('recommendation'):
                prompt += f"  정책 부합도: {pa['recommendation']}\n"
        else:
            prompt += "  (지역 트렌드 데이터 없음)\n"

        # 투찰률 최적화 분석
        bid_rate = structured_analysis.get('bid_rate_optimization', {})
        prompt += """
═══════════════════════════════════════
▶ 7. 투찰률 최적화 분석 데이터
═══════════════════════════════════════
"""
        if bid_rate and not bid_rate.get('error'):
            rec = bid_rate.get('recommended_rate', {})
            optimal = rec.get('optimal', '')
            range_low = rec.get('range_low', '')
            range_high = rec.get('range_high', '')
            confidence = rec.get('confidence', 0)
            source = rec.get('source', '')
            if optimal:
                prompt += f"  추천 투찰률: {optimal}%\n"
            if range_low and range_high:
                prompt += f"  투찰률 범위: {range_low}% ~ {range_high}%\n"
            if confidence:
                prompt += f"  신뢰도: {confidence * 100:.0f}%\n"
            if source:
                prompt += f"  데이터 출처: {source}\n"
            # 기관별 데이터
            by_org = bid_rate.get('by_org', {})
            if by_org.get('org_avg_rate'):
                prompt += f"  발주기관 평균 투찰률: {by_org['org_avg_rate']}% ({by_org.get('org_data_count', 0)}건)\n"
            # 위험도 평가
            risk = bid_rate.get('risk_assessment', {})
            if risk.get('strategy'):
                prompt += f"  전략 가이드: {risk['strategy']}\n"
        else:
            prompt += "  (투찰률 최적화 데이터 없음)\n"

        # RFP 전년 대비 변화점
        rfp_changes = structured_analysis.get('rfp_changes', {})
        prompt += """
═══════════════════════════════════════
▶ 8. RFP 전년 대비 변화점
═══════════════════════════════════════
"""
        if rfp_changes.get('key_changes'):
            diff_summary = rfp_changes.get('diff_summary', {})
            prompt += (
                f"  유사도: {diff_summary.get('similarity_ratio', 0) * 100:.1f}%, "
                f"변경 {diff_summary.get('changed_count', 0)}건\n"
            )
            for i, change in enumerate(rfp_changes['key_changes'][:10], 1):
                change_type = change.get('type', '')
                content = change.get('content', '')[:200]
                type_label = {'added': '추가', 'removed': '삭제', 'modified': '수정'}.get(
                    change_type, change_type
                )
                prompt += f"  {i}. [{type_label}] {content}\n"
        elif rfp_changes.get('past_bid'):
            past = rfp_changes['past_bid']
            prompt += f"  유사 과거 입찰: {past.get('bid_title', '')} (유사도: {past.get('similarity', 0) * 100:.1f}%)\n"
            if rfp_changes.get('note'):
                prompt += f"  참고: {rfp_changes['note']}\n"
        else:
            note = rfp_changes.get('note', 'RFP 변화 데이터 없음')
            prompt += f"  {note}\n"

        # 과거 낙찰 이력
        past_awards = structured_analysis.get('past_awards', [])
        if past_awards:
            prompt += """
═══════════════════════════════════════
▶ 9. 과거 유사 사업 낙찰 이력
═══════════════════════════════════════
"""
            for i, award in enumerate(past_awards[:10], 1):
                award_title = award.get('bid_title', '')
                winner = award.get('winner_name', '')
                amount = award.get('award_amount', '')
                rate = award.get('bid_rate', '')
                date = award.get('award_date', '')
                prompt += f"  {i}. [{date}] {award_title}\n"
                prompt += f"     - 낙찰업체: {winner}\n"
                if amount:
                    prompt += f"     - 낙찰금액: {amount}\n"
                if rate:
                    prompt += f"     - 투찰률: {rate}%\n"

        # 적격심사 및 정량평가 시뮬레이션 결과 추가
        bid_sim = structured_analysis.get('bid_simulator', {})
        prompt += """
═══════════════════════════════════════
▶ 10. 적격심사 및 정량평가 시뮬레이션 데이터
═══════════════════════════════════════
"""
        if bid_sim and not bid_sim.get('error'):
            scorecard = bid_sim.get('scorecard', {})
            prompt += f"  종합 정량평가 점수: {scorecard.get('total_score', 0)}점 (통과 안정 기준: {scorecard.get('pass_threshold', 0)}점)\n"
            prompt += f"  진단 상태: {scorecard.get('status', '정보 없음')}\n"
            
            credit = scorecard.get('credit_evaluation', {})
            prompt += f"  · 경영상태 평가: {credit.get('score', 0)}/{credit.get('max_score', 0)}점 (신용등급: {credit.get('rating', 'N/A')})\n"
            
            exp = scorecard.get('experience_evaluation', {})
            prompt += f"  · 유사실적 평가: {exp.get('score', 0)}/{exp.get('max_score', 0)}점 (최근 3년 누적: {exp.get('similar_experience_total_krw', 0):,}원)\n"
            
            va = scorecard.get('value_added', {})
            prompt += f"  · 신인도 가점: {va.get('score', 0)}점 (항목: {', '.join(va.get('reasons', []))})\n"
            
            strategies = bid_sim.get('strategies', [])
            if strategies:
                prompt += "  · 정량적 부족 점수 극복을 위한 추천 전략:\n"
                for s in strategies:
                    prompt += f"    - {s}\n"
        else:
            prompt += "  (적격심사 시뮬레이션 데이터 없음)\n"

        prompt += """
═══════════════════════════════════════

위 모든 데이터(공고 정보 + 사전 분석 6종 + 과거 이력 + 적격심사 시뮬레이션 결과)를
종합하여 고도화된 입찰 전략을 JSON 형식으로 분석해 주세요.

## 특히 주의사항:
1. 경쟁사 데이터가 있다면, 주요 경쟁사의 강점/약점을 구체적으로 분석하세요.
2. 투찰률 최적화 데이터를 예산 분석에 반드시 반영하세요.
3. RFP 변화점이 있다면, 이를 차별화 전략의 핵심으로 삼으세요.
4. 발주기관 정책 방향을 제안서 기획의 배경/목적에 연계하세요.
5. 지역 트렌드를 반영한 시의성 있는 전략을 수립하세요.
6. 적격심사 시뮬레이션 결과(scorecard_feedback)를 검토하고, 정량점수가 부족할 경우 극복할 구체적 행동(컨소시엄 지분 배분, 가점 인증 확보 등)을 종합 권고와 기획에 반영하세요.
7. 제안요청서(RFP)를 기준으로 핵심 가치 제안(win_themes)과 요구사항 대응 현황표(compliance_matrix)를 생성하세요.
"""
        return prompt

