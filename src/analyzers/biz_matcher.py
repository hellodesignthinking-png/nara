"""
사업자-공고 매칭 엔진 ⭐ 핵심 모듈

등록된 여러 사업자 중 각 공고에 가장 적합한 사업자를 매칭합니다.
업종 적합성, 자격/면허, 예산 범위, 지역, 과거 실적 등
5개 기준을 가중 평가하여 종합 매칭 점수를 산출합니다.
"""

import logging
import re
from typing import Optional
from src.utils.formatters import safe_float

logger = logging.getLogger(__name__)


class BizMatcher:
    """
    사업자-공고 매칭 엔진

    5대 매칭 기준:
    - 업종 적합성 (30%): 공고 카테고리와 사업자 업종 매칭
    - 자격/면허 (25%): 공고 요구 자격과 보유 면허 비교
    - 지역 (20%): 지역제한 공고의 사업자 소재지 확인
    - 예산 범위 (15%): 공고 예산이 사업자 참여 가능 범위 내
    - 과거 실적/키워드 (10%): 유사 사업 수행 경험

    사업자 프로필 구조 예시:
        {
            'name': '(주)테크솔루션',
            'business_types': ['SW개발', '시스템통합', 'AI'],
            'licenses': ['소프트웨어사업자', '정보통신공사업'],
            'budget_range': {'min': 5000, 'max': 500000},  # 만원 단위
            'region': '서울특별시',
            'past_projects': [
                {'name': 'AI 데이터 분석 플랫폼 구축', 'amount': 120000, 'year': 2024},
                {'name': '공공 빅데이터 시스템 개발', 'amount': 85000, 'year': 2023},
            ],
        }

    공고 구조 예시:
        {
            'title': '인공지능 기반 민원분석 시스템 구축',
            'category': 'SW개발',
            'required_licenses': ['소프트웨어사업자'],
            'budget': 150000,  # 만원 단위
            'region': '서울특별시',
            'description': '...',
        }
    """

    # ──────────────────────────────────────────────
    # 가중치 설정
    # ──────────────────────────────────────────────
    DEFAULT_WEIGHTS = {
        'business_type': 0.30,  # 업종 적합성
        'license': 0.25,        # 자격/면허
        'region': 0.20,         # 지역
        'budget_range': 0.15,   # 예산 범위
        'keyword': 0.10,        # 키워드 (과거 실적 기반)
    }

    # 내부 매핑: DEFAULT_WEIGHTS 키 → 코드 내부 사용 키
    _WEIGHT_KEY_MAP = {
        'business_type': 'business_type',
        'license': 'license',
        'budget': 'budget_range',
        'region': 'region',
        'experience': 'keyword',
    }

    @classmethod
    def _weight(cls, internal_key: str) -> float:
        """내부 키에 대한 가중치를 반환합니다."""
        dw_key = cls._WEIGHT_KEY_MAP.get(internal_key, internal_key)
        return cls.DEFAULT_WEIGHTS[dw_key]

    # ──────────────────────────────────────────────
    # 업종 유사어 사전
    # 같은 그룹에 속한 업종은 서로 유사한 것으로 간주
    # ──────────────────────────────────────────────
    BUSINESS_TYPE_SYNONYMS: dict[str, set[str]] = {
        'IT_SW': {
            'SW개발', '소프트웨어', 'IT', 'SI', '시스템통합', '프로그램개발',
            '소프트웨어개발', '정보시스템', '정보기술', '응용SW', '시스템SW',
            '솔루션', '웹개발', '앱개발', '모바일개발',
        },
        'AI_DATA': {
            'AI', '인공지능', '머신러닝', '딥러닝', '데이터', '빅데이터',
            '데이터분석', '데이터사이언스', 'ML', 'DL', '기계학습',
            '자연어처리', 'NLP', '컴퓨터비전',
        },
        'CLOUD_INFRA': {
            '클라우드', 'IaaS', 'SaaS', 'PaaS', '인프라', 'IDC',
            '서버', '네트워크', '정보통신', '통신',
        },
        'SECURITY': {
            '보안', '정보보안', '사이버보안', 'ISMS', '개인정보보호',
            '보안관제', '취약점진단', '암호화',
        },
        'CONSULTING': {
            '컨설팅', '자문', '연구용역', '정책연구', 'ISP', 'ISMP',
            'BPR', '전략수립', '기획',
        },
        'MARKETING': {
            '마케팅', '홍보', '광고', '브랜딩', 'PR', '캠페인',
            '디자인', '콘텐츠', '미디어', '영상제작',
        },
        'CONSTRUCTION': {
            '건설', '토목', '건축', '시설물', '전기공사', '기계설비',
            '소방', '조경',
        },
    }

    # ──────────────────────────────────────────────
    # 지역 계층 구조 (시/도 → 시/군/구 매핑)
    # 같은 시/도 소속이면 부분 점수 부여
    # ──────────────────────────────────────────────
    REGION_HIERARCHY: dict[str, list[str]] = {
        '서울특별시': ['서울', '서울시', '서울특별시'],
        '경기도': ['경기', '경기도', '수원', '성남', '고양', '용인', '부천', '안산', '안양', '화성', '평택'],
        '인천광역시': ['인천', '인천시', '인천광역시'],
        '부산광역시': ['부산', '부산시', '부산광역시'],
        '대구광역시': ['대구', '대구시', '대구광역시'],
        '광주광역시': ['광주', '광주시', '광주광역시'],
        '대전광역시': ['대전', '대전시', '대전광역시'],
        '울산광역시': ['울산', '울산시', '울산광역시'],
        '세종특별자치시': ['세종', '세종시', '세종특별자치시'],
        '강원도': ['강원', '강원도', '춘천', '원주', '강릉'],
        '충청북도': ['충북', '충청북도', '청주', '충주'],
        '충청남도': ['충남', '충청남도', '천안', '아산'],
        '전라북도': ['전북', '전라북도', '전주', '익산', '군산'],
        '전라남도': ['전남', '전라남도', '목포', '여수', '순천'],
        '경상북도': ['경북', '경상북도', '포항', '구미', '경주'],
        '경상남도': ['경남', '경상남도', '창원', '김해', '진주'],
        '제주특별자치도': ['제주', '제주도', '제주특별자치도'],
    }

    def __init__(self):
        """매칭 엔진을 초기화합니다."""
        # 업종 유사어의 역방향 인덱스 생성 (빠른 룩업용)
        self._type_to_group: dict[str, str] = {}
        for group_name, synonyms in self.BUSINESS_TYPE_SYNONYMS.items():
            for synonym in synonyms:
                self._type_to_group[synonym.upper()] = group_name

        # 지역 역방향 인덱스 생성
        self._region_to_parent: dict[str, str] = {}
        for parent, children in self.REGION_HIERARCHY.items():
            for child in children:
                self._region_to_parent[child] = parent

    # ══════════════════════════════════════════════
    # 공개 API
    # ══════════════════════════════════════════════

    def calculate_match_score(self, business_profile: dict, bid: dict, ai_settings: Optional[dict] = None) -> dict:
        """
        사업자와 공고의 매칭 점수를 계산합니다.

        Args:
            business_profile: 사업자 프로필 dict
            bid: 공고 정보 dict

        Returns:
            {
                'total_score': 75.5,
                'breakdown': {
                    'business_type': {'score': 90, 'weight': 0.3, 'detail': '...'},
                    'license': {'score': 80, 'weight': 0.25, 'detail': '...'},
                    'budget': {'score': 100, 'weight': 0.15, 'detail': '...'},
                    'region': {'score': 50, 'weight': 0.15, 'detail': '...'},
                    'experience': {'score': 30, 'weight': 0.15, 'detail': '...'},
                    'credit_sanction_adjust': {'score': 2.0, 'weight': 1.0, 'detail': '...'},
                },
                'recommendation': '참여 적극 권장' | '참여 검토' | '참여 부적합'
            }
        """
        if not business_profile or not bid:
            logger.warning("빈 business_profile 또는 bid가 전달됨")
            return {
                'total_score': 0.0,
                'breakdown': {},
                'recommendation': '데이터 누락',
            }

        try:
            breakdown = {}

            # 1. 업종 적합성 평가
            breakdown['business_type'] = self._evaluate_business_type(
                business_profile, bid
            )

            # 2. 자격/면허 평가
            breakdown['license'] = self._evaluate_license(
                business_profile, bid
            )

            # 3. 예산 범위 평가
            breakdown['budget'] = self._evaluate_budget(
                business_profile, bid
            )

            # 4. 지역 평가
            breakdown['region'] = self._evaluate_region(
                business_profile, bid
            )

            # 5. 과거 실적 평가
            breakdown['experience'] = self._evaluate_experience(
                business_profile, bid
            )

            # 개인 AI 설정에 따른 가중치 덮어쓰기
            if ai_settings:
                rel_w = ai_settings.get("relevance_weight", 0.35)
                cap_w = ai_settings.get("capacity_weight", 0.35)
                
                total_w = rel_w + cap_w
                if total_w > 0:
                    rel_norm = rel_w / total_w
                    cap_norm = cap_w / total_w
                else:
                    rel_norm = 0.5
                    cap_norm = 0.5
                
                # relevance_weight 쪼개기 (기본 비율 30 : 25 : 20)
                breakdown['business_type']['weight'] = rel_norm * 0.40
                breakdown['license']['weight'] = rel_norm * 0.333
                breakdown['region']['weight'] = rel_norm * 0.267
                
                # capacity_weight 쪼개기 (기본 비율 15 : 10)
                breakdown['budget']['weight'] = cap_norm * 0.60
                breakdown['experience']['weight'] = cap_norm * 0.40

            # 종합 점수 계산 (가중 평균)
            total_score = sum(
                breakdown[key]['score'] * breakdown[key]['weight']
                for key in breakdown
            )

            # 6. 신인도 및 적격심사 가감점 적용 (정량 평가 보정)
            adjustment_score = 0.0
            adjustment_details = []

            # 6-1. 신용평가등급 보정
            credit_rating = business_profile.get("credit_rating", "BBB")
            if credit_rating:
                credit_rating_upper = credit_rating.upper()
                if credit_rating_upper in ["AAA", "AA+", "AA", "AA-", "A+", "A", "A-"]:
                    adjustment_score += 2.0
                    adjustment_details.append(f"우수 신용등급({credit_rating_upper}) 가산 (+2.0)")
                elif credit_rating_upper in ["B+", "B", "B-", "CCC+", "C"]:
                    adjustment_score -= 5.0
                    adjustment_details.append(f"취약 신용등급({credit_rating_upper}) 감점 (-5.0)")

            # 6-2. 우대 기업 유형 보정 (여성기업, 장애인기업, 사회적협동조합 등)
            company_type = business_profile.get("company_type", "")
            if company_type:
                has_benefit = False
                for kw in ["여성", "장애인", "사회적", "협동조합", "스타트업", "창업"]:
                    if kw in company_type:
                        has_benefit = True
                        break
                if has_benefit:
                    adjustment_score += 3.0
                    adjustment_details.append(f"기업우대 가산 (+3.0)")

            # 6-3. 부정당업자 제재이력 감점
            if business_profile.get("has_sanctions", False):
                adjustment_score -= 10.0
                adjustment_details.append("부정당업자 처분이력 감점 (-10.0)")

            # 신용 가중치에 따른 가감점 배수 조절
            if ai_settings:
                cred_w = ai_settings.get("credit_weight", 0.30)
                adjustment_score = adjustment_score * (cred_w / 0.30)

            total_score += adjustment_score
            # 최소 0점, 최대 100점 제한
            total_score = max(0.0, min(100.0, round(total_score, 1)))

            # 신인도 평가 항목 breakdown에 명시
            breakdown['credit_sanction_adjust'] = {
                'score': adjustment_score,
                'weight': 1.0,
                'detail': ', '.join(adjustment_details) if adjustment_details else '특이사항 없음'
            }

            # 종합 권고 생성
            recommendation = self._generate_recommendation(total_score, breakdown)

            return {
                'total_score': total_score,
                'breakdown': breakdown,
                'recommendation': recommendation,
            }
        except Exception as e:
            logger.error("매칭 점수 계산 중 오류 발생: %s", e, exc_info=True)
            return {
                'total_score': 0.0,
                'breakdown': {},
                'recommendation': '매칭 점수 계산 실패',
            }

    def find_best_match(self, businesses: list[dict], bid: dict, ai_settings: Optional[dict] = None) -> list[dict]:
        """
        여러 사업자 중 해당 공고에 가장 적합한 사업자를 순위별로 반환합니다.

        Args:
            businesses: 사업자 프로필 목록
            bid: 공고 정보
            ai_settings: 개인 AI 에이전트 설정

        Returns:
            [{'business': {...}, 'score': 85.0, 'breakdown': {...}, 'recommendation': '...'}, ...]
            점수 내림차순 정렬
        """
        results = []
        for biz in businesses:
            match_result = self.calculate_match_score(biz, bid, ai_settings)
            results.append({
                'business': biz,
                'score': match_result['total_score'],
                'breakdown': match_result['breakdown'],
                'recommendation': match_result['recommendation'],
            })

        # 점수 내림차순 정렬
        results.sort(key=lambda x: x['score'], reverse=True)
        return results

    def match_all_bids(self, businesses: list[dict], bids: list[dict], ai_settings: Optional[dict] = None) -> list[dict]:
        """
        모든 공고에 대해 모든 사업자 매칭을 수행합니다.

        Args:
            businesses: 사업자 프로필 목록
            bids: 공고 목록
            ai_settings: 개인 AI 에이전트 설정

        Returns:
            [
                {
                    'bid': {...},
                    'best_match': {'business': {...}, 'score': 85.0, ...},
                    'all_matches': [{'business': {...}, 'score': 85.0, ...}, ...],
                },
                ...
            ]
        """
        results = []
        for bid in bids:
            all_matches = self.find_best_match(businesses, bid, ai_settings)
            best_match = all_matches[0] if all_matches else None

            results.append({
                'bid': bid,
                'best_match': best_match,
                'all_matches': all_matches,
            })

        return results

    # ══════════════════════════════════════════════
    # 개별 평가 기준 구현
    # ══════════════════════════════════════════════

    def _evaluate_business_type(self, biz: dict, bid: dict) -> dict:
        """
        업종 적합성을 평가합니다. (가중치 30%)

        유사어 사전을 활용하여 공고 카테고리/제목과 사업자 업종을 유연하게 매칭합니다.
        - 정확히 일치: 100점
        - 같은 그룹(유사어): 80점
        - 관련 그룹(제목에서 유사어 발견): 50점
        - 매칭 없음: 10점 (기본점수)
        """
        biz_types = biz.get('business_types', [])
        bid_category = bid.get('category', '')
        bid_title = bid.get('title', bid.get('bidNtceNm', ''))
        bid_title_upper = bid_title.upper() if bid_title else ''

        if not biz_types:
            return {
                'score': 10, 'weight': self._weight('business_type'),
                'detail': '사업자 업종 정보가 없습니다.'
            }

        best_score = 10
        detail_parts = []

        # 공고 카테고리와 직접 비교
        for btype in biz_types:
            # 정확 일치
            if bid_category and btype.upper() == bid_category.upper():
                best_score = max(best_score, 100)
                detail_parts.append(f"'{btype}' 업종이 공고 카테고리 '{bid_category}'와 정확히 일치")
                break

            # 유사어 그룹 일치
            btype_group = self._type_to_group.get(btype.upper())
            category_group = self._type_to_group.get(bid_category.upper()) if bid_category else None

            if btype_group and category_group and btype_group == category_group:
                best_score = max(best_score, 80)
                detail_parts.append(f"'{btype}' 업종이 공고 카테고리 '{bid_category}'와 유사 업종 그룹")

            # 공고 제목에서 업종 키워드 검색
            if bid_title:
                btype_group_synonyms = self.BUSINESS_TYPE_SYNONYMS.get(
                    btype_group, set()
                ) if btype_group else {btype}

                for synonym in btype_group_synonyms:
                    if synonym.upper() in bid_title_upper:
                        best_score = max(best_score, 50)
                        detail_parts.append(f"공고 제목에서 '{synonym}' 키워드 발견")
                        break

        detail = '; '.join(detail_parts) if detail_parts else '관련 업종 매칭 없음'
        return {
            'score': best_score,
            'weight': self._weight('business_type'),
            'detail': detail,
        }

    def _evaluate_license(self, biz: dict, bid: dict) -> dict:
        """
        자격/면허 보유 여부를 평가합니다. (가중치 25%)

        - 요구 자격 없음: 100점
        - 모든 요구 자격 보유: 100점
        - 일부 보유: 비율에 따라 점수 계산
        - 전혀 미보유: 0점 (치명적)
        """
        required_licenses = bid.get('required_licenses', [])
        held_licenses = biz.get('licenses', [])

        # 요구 자격이 없는 공고
        if not required_licenses:
            return {
                'score': 100, 'weight': self._weight('license'),
                'detail': '별도 자격/면허 요구사항 없음',
            }

        if not held_licenses:
            return {
                'score': 0, 'weight': self._weight('license'),
                'detail': f"요구 자격 {required_licenses}을 보유하지 않음 (보유 면허 없음)",
            }

        # 부분 일치를 포함한 자격 매칭
        matched = []
        unmatched = []

        for req in required_licenses:
            found = False
            for held in held_licenses:
                # 부분 문자열 매칭 (예: '소프트웨어' in '소프트웨어사업자')
                if (req.upper() in held.upper()) or (held.upper() in req.upper()):
                    matched.append(f"{req} ✔ ({held})")
                    found = True
                    break
            if not found:
                unmatched.append(req)

        match_ratio = len(matched) / len(required_licenses)
        score = round(match_ratio * 100)

        detail_parts = []
        if matched:
            detail_parts.append(f"보유: {', '.join(matched)}")
        if unmatched:
            detail_parts.append(f"미보유: {', '.join(unmatched)}")

        return {
            'score': score,
            'weight': self._weight('license'),
            'detail': '; '.join(detail_parts),
        }

    def _evaluate_budget(self, biz: dict, bid: dict) -> dict:
        """
        예산 범위 적합성을 평가합니다. (가중치 15%)

        - 사업자 참여 가능 범위 내: 100점
        - 범위를 약간 벗어남 (±30%): 50점
        - 범위를 크게 벗어남: 20점
        - 예산 정보 없음: 70점 (중립)
        """
        budget_range = biz.get('budget_range', {})
        bid_budget = safe_float(bid.get('budget', 0))

        # 예산 정보가 없는 경우
        if not bid_budget:
            return {
                'score': 70, 'weight': self._weight('budget'),
                'detail': '공고 예산 정보 미공개',
            }

        if not budget_range:
            return {
                'score': 70, 'weight': self._weight('budget'),
                'detail': '사업자 참여 가능 예산 범위 미설정',
            }

        min_budget = budget_range.get('min', 0)
        max_budget = budget_range.get('max', float('inf'))

        # bid_budget은 이미 safe_float로 변환됨 — 추가 문자열 처리 불필요

        if min_budget <= bid_budget <= max_budget:
            score = 100
            max_str = f"{max_budget:,.0f}" if max_budget < 999999999999 else "제한없음"
            detail = f"공고 예산 {bid_budget:,.0f}만원이 참여 가능 범위 내 ({min_budget:,.0f}~{max_str}만원)"
        elif bid_budget < min_budget:
            # 최소 예산보다 작은 경우
            ratio = bid_budget / min_budget if min_budget > 0 else 0
            if ratio >= 0.7:
                score = 50
                detail = f"공고 예산 {bid_budget:,.0f}만원이 최소 범위({min_budget:,.0f}만원)보다 약간 부족"
            else:
                score = 20
                detail = f"공고 예산 {bid_budget:,.0f}만원이 최소 범위({min_budget:,.0f}만원)보다 크게 부족"
        else:
            # 최대 예산보다 큰 경우
            ratio = max_budget / bid_budget if bid_budget > 0 else 0
            if ratio >= 0.7:
                score = 50
                max_str = f"{max_budget:,.0f}" if max_budget < 999999999999 else "제한없음"
                detail = f"공고 예산 {bid_budget:,.0f}만원이 최대 범위({max_str}만원)보다 약간 초과"
            else:
                score = 20
                max_str = f"{max_budget:,.0f}" if max_budget < 999999999999 else "제한없음"
                detail = f"공고 예산 {bid_budget:,.0f}만원이 최대 범위({max_str}만원)를 크게 초과"

        return {
            'score': score, 'weight': self._weight('budget'),
            'detail': detail,
        }

    def _evaluate_region(self, biz: dict, bid: dict) -> dict:
        """
        지역 적합성을 평가합니다. (가중치 15%)

        - 지역 제한 없음: 100점
        - 동일 지역: 100점
        - 동일 시/도: 70점
        - 다른 지역: 30점
        """
        bid_region = bid.get('region', '')
        biz_region = biz.get('region', '')

        # 지역 제한이 없는 공고
        if not bid_region or bid_region in ('전국', '제한없음', '해당없음'):
            return {
                'score': 100, 'weight': self._weight('region'),
                'detail': '지역 제한 없음',
            }

        if not biz_region:
            return {
                'score': 50, 'weight': self._weight('region'),
                'detail': '사업자 소재지 정보 없음',
            }

        # 정확 일치
        if biz_region == bid_region:
            return {
                'score': 100, 'weight': self._weight('region'),
                'detail': f"소재지 '{biz_region}'이 공고 지역과 일치",
            }

        # 같은 시/도 소속인지 확인
        biz_parent = self._region_to_parent.get(biz_region, biz_region)
        bid_parent = self._region_to_parent.get(bid_region, bid_region)

        if biz_parent == bid_parent:
            return {
                'score': 70, 'weight': self._weight('region'),
                'detail': f"소재지 '{biz_region}'이 동일 시/도({biz_parent}) 내",
            }

        return {
            'score': 30, 'weight': self._weight('region'),
            'detail': f"소재지 '{biz_region}'이 공고 지역 '{bid_region}'과 불일치",
        }

    def _evaluate_experience(self, biz: dict, bid: dict) -> dict:
        """
        과거 실적을 평가합니다. (가중치 15%)

        유사 사업 수행 경험을 키워드 기반으로 확인합니다.
        - 매우 유사한 실적 있음: 100점
        - 관련 실적 있음: 60점
        - 실적은 있으나 관련성 낮음: 30점
        - 실적 없음: 10점
        """
        past_projects = biz.get('past_projects', [])
        bid_title = bid.get('title', bid.get('bidNtceNm', ''))
        bid_category = bid.get('category', '')

        if not past_projects:
            return {
                'score': 10, 'weight': self._weight('experience'),
                'detail': '등록된 과거 수행 실적 없음',
            }

        # 공고 제목에서 핵심 키워드 추출
        bid_keywords = self._extract_keywords(bid_title)
        if bid_category:
            bid_keywords.add(bid_category.upper())

        best_score = 10
        best_project = None
        detail = '관련 실적 없음'

        for project in past_projects:
            proj_name = project.get('name', '')
            proj_keywords = self._extract_keywords(proj_name)

            # 키워드 교집합으로 유사도 계산
            if bid_keywords and proj_keywords:
                overlap = bid_keywords & proj_keywords
                similarity = len(overlap) / max(len(bid_keywords), 1)

                if similarity >= 0.5:
                    score = 100
                elif similarity >= 0.3:
                    score = 80
                elif similarity >= 0.1:
                    score = 60
                else:
                    # 유사어 그룹 기반 매칭 시도
                    score = self._group_based_similarity(bid_keywords, proj_keywords)
            else:
                score = 30  # 키워드 추출 불가 시 기본 점수

            if score > best_score:
                best_score = score
                best_project = project

        if best_project:
            proj_info = best_project.get('name', '알 수 없음')
            proj_year = best_project.get('year', '')
            proj_amount = best_project.get('amount', 0)
            detail = f"유사 실적: '{proj_info}'"
            if proj_year:
                detail += f" ({proj_year}년)"
            if proj_amount:
                detail += f" {safe_float(proj_amount):,.0f}만원"

        return {
            'score': best_score,
            'weight': self._weight('experience'),
            'detail': detail,
        }

    # ══════════════════════════════════════════════
    # 유틸리티 메서드
    # ══════════════════════════════════════════════

    def _extract_keywords(self, text: str) -> set[str]:
        """텍스트에서 의미있는 키워드를 추출합니다."""
        if not text:
            return set()

        # 불용어 (제거할 단어들)
        # 주의: '시스템', '구축', '개발', '사업', '용역', '관리', '운영', '지원' 등은
        # 나라장터 공공조달 도메인에서 핵심 키워드이므로 불용어에 포함하지 않음
        stopwords = {
            '서비스', '기반', '위한', '관련', '활용', '등', '및', '의', '을', '를',
            '에', '대한', '통한', '추진', '수행', '계획', '방안', '연구',
        }

        # 영문+한글 단어 추출
        words = re.findall(r'[가-힣]{2,}|[A-Za-z]{2,}', text)
        keywords = set()

        for word in words:
            upper_word = word.upper()
            if word not in stopwords and len(word) >= 2:
                keywords.add(upper_word)
                # 유사어 그룹도 추가
                group = self._type_to_group.get(upper_word)
                if group:
                    keywords.add(group)

        return keywords

    def _group_based_similarity(self, kw_set1: set[str], kw_set2: set[str]) -> int:
        """유사어 그룹 기반 유사도를 계산합니다."""
        groups1 = {self._type_to_group.get(kw, kw) for kw in kw_set1}
        groups2 = {self._type_to_group.get(kw, kw) for kw in kw_set2}

        overlap = groups1 & groups2
        if overlap:
            return 40
        return 10


    def _generate_recommendation(self, total_score: float, breakdown: dict) -> str:
        """
        종합 점수와 세부 평가를 기반으로 참여 권고를 생성합니다.

        단순 점수 기준 외에 치명적 결격 사유도 확인합니다:
        - 필수 자격 미보유 → 무조건 '참여 부적합'
        - 부정당업자 제재 이력이 있으면 경고 포함
        """
        # 치명적 결격 사유 확인
        license_score = breakdown.get('license', {}).get('score', 100)
        if license_score == 0:
            return '참여 부적합 (필수 자격 미보유)'

        # 제재이력 여부 확인 (신인도 보정에 -10점 감점이 있는 경우)
        adjust_detail = breakdown.get('credit_sanction_adjust', {}).get('detail', '')
        has_sanctions = '부정당업자' in adjust_detail

        # 종합 점수 기반 판단
        if total_score >= 70:
            return '참여 적극 권장' if not has_sanctions else '참여 검토 (제재이력 주의)'
        elif total_score >= 45:
            return '참여 검토'
        else:
            return '참여 부적합'
