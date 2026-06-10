"""
키워드 기반 1차 스크리닝 모듈

공고 제목과 내용에서 관심 키워드를 매칭하여 관련도 점수를 산출합니다.
TF-IDF 대신 가중 키워드 매칭 방식을 사용하여 빠르고 직관적인 필터링을 제공합니다.
"""

import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class MatchResult:
    """키워드 매칭 결과를 담는 데이터 클래스"""
    keyword: str           # 매칭된 키워드
    found_in: str          # 발견 위치 ('title' 또는 'description')
    frequency: int         # 출현 빈도
    weight: float          # 가중치 (제목=3.0, 내용=1.0)


class KeywordFilter:
    """
    키워드 기반 공고 필터링 엔진

    관심 키워드 목록을 기반으로 공고의 관련도 점수(0~100)를 계산합니다.
    제목에 키워드가 등장하면 높은 가중치, 내용에만 있으면 낮은 가중치를 부여합니다.
    """

    # 제목과 내용의 키워드 매칭 가중치
    TITLE_WEIGHT = 3.0
    DESCRIPTION_WEIGHT = 1.0

    # 연속 매칭 보너스 (여러 키워드가 매칭될수록 점수 상승)
    MULTI_KEYWORD_BONUS = 1.2

    def __init__(self, keywords: list[str]):
        """
        관심 키워드 목록으로 초기화합니다.

        Args:
            keywords: 관심 키워드 목록 (예: ['AI', '인공지능', '데이터', '마케팅'])
        """
        # 키워드를 소문자로 정규화하여 저장
        self.keywords = [kw.strip() for kw in keywords if kw.strip()]

        # 정규식 패턴 캐시 (키워드 → 컴파일된 패턴)
        self._regex_cache: dict[str, re.Pattern] = {}

        # 유사어 사전: 같은 개념을 나타내는 키워드를 그룹으로 묶음
        # 유사어 중 하나가 매칭되면 해당 그룹의 모든 키워드가 매칭된 것으로 처리
        self.synonym_groups: dict[str, list[str]] = {
            'AI': ['AI', '인공지능', '머신러닝', '딥러닝', 'ML', 'DL', '기계학습'],
            '데이터': ['데이터', '빅데이터', '데이터분석', '데이터베이스', 'DB', 'DW'],
            'SW개발': ['SW개발', '소프트웨어', 'IT', '정보시스템', 'SI', '시스템통합', '프로그램'],
            '클라우드': ['클라우드', 'IaaS', 'SaaS', 'PaaS', 'AWS', 'Azure'],
            '보안': ['보안', '정보보안', '사이버보안', 'ISMS', '개인정보'],
            '컨설팅': ['컨설팅', '자문', '용역', '연구용역', '정책연구'],
            '마케팅': ['마케팅', '홍보', '광고', '브랜딩', 'PR', '캠페인'],
            '플랫폼': ['플랫폼', '포털', '시스템구축', '웹사이트', '앱개발'],
        }

        # 각 키워드에 대해 유사어를 확장한 검색 패턴을 미리 생성
        self._expanded_keywords = self._expand_keywords()

    def _expand_keywords(self) -> dict[str, list[str]]:
        """
        키워드를 유사어 사전을 기반으로 확장합니다.

        Returns:
            {원본_키워드: [원본_키워드, 유사어1, 유사어2, ...]}
        """
        expanded = {}
        for keyword in self.keywords:
            # 유사어 그룹에서 해당 키워드가 포함된 그룹 찾기
            synonyms = [keyword]  # 자기 자신은 항상 포함
            for _group_name, group_words in self.synonym_groups.items():
                # 키워드가 유사어 그룹에 포함되어 있으면 해당 그룹 전체를 추가
                if any(keyword.upper() == w.upper() for w in group_words):
                    synonyms.extend(
                        w for w in group_words
                        if w.upper() != keyword.upper()
                    )
                    break
            expanded[keyword] = list(set(synonyms))
        return expanded

    def _get_pattern(self, keyword: str) -> re.Pattern:
        """키워드에 대한 컴파일된 정규식 패턴을 캐시에서 가져오거나 생성합니다."""
        if keyword not in self._regex_cache:
            self._regex_cache[keyword] = re.compile(
                re.escape(keyword), re.IGNORECASE
            )
        return self._regex_cache[keyword]

    def _count_keyword_occurrences(self, text: str, keyword: str) -> int:
        """
        텍스트에서 키워드의 출현 빈도를 계산합니다.
        대소문자 무시, 부분 일치 허용

        Args:
            text: 검색 대상 텍스트
            keyword: 검색할 키워드

        Returns:
            출현 횟수
        """
        if not text or not keyword:
            return 0
        pattern = self._get_pattern(keyword)
        return len(pattern.findall(text))

    def _calculate_match_internal(self, title: str, description: str = '') -> tuple[list['MatchResult'], set[str]]:
        """
        제목/내용에서 키워드 매칭을 수행하는 내부 공통 메서드.

        calculate_relevance()와 get_match_details() 양쪽에서 호출하여
        중복 로직을 제거합니다.

        Args:
            title: 공고 제목
            description: 공고 내용 (선택)

        Returns:
            (매칭 결과 리스트, 매칭된 키워드 집합) 튜플
        """
        matches: list[MatchResult] = []
        matched_keywords: set[str] = set()

        for keyword, synonyms in self._expanded_keywords.items():
            keyword_matched = False

            for synonym in synonyms:
                # 제목에서 검색
                title_count = self._count_keyword_occurrences(title, synonym)
                if title_count > 0:
                    matches.append(MatchResult(
                        keyword=keyword,
                        found_in='title',
                        frequency=title_count,
                        weight=self.TITLE_WEIGHT,
                    ))
                    keyword_matched = True

                # 내용에서 검색
                desc_count = self._count_keyword_occurrences(description, synonym)
                if desc_count > 0:
                    matches.append(MatchResult(
                        keyword=keyword,
                        found_in='description',
                        frequency=desc_count,
                        weight=self.DESCRIPTION_WEIGHT,
                    ))
                    keyword_matched = True

            if keyword_matched:
                matched_keywords.add(keyword)

        return matches, matched_keywords

    def calculate_relevance(self, title: str, description: str = '') -> float:
        """
        공고 제목/내용에서 키워드를 매칭하여 관련도 점수(0~100)를 계산합니다.

        점수 계산 로직:
        1. 각 키워드(+ 유사어)의 출현 여부를 제목과 내용에서 검사
        2. 제목 매칭은 TITLE_WEIGHT(3.0), 내용 매칭은 DESCRIPTION_WEIGHT(1.0) 적용
        3. 빈도수에 따른 보너스 (최대 2배)
        4. 여러 키워드가 동시에 매칭되면 MULTI_KEYWORD_BONUS(1.2배) 적용
        5. 최종 점수를 0~100 범위로 정규화

        Args:
            title: 공고 제목
            description: 공고 내용 (선택)

        Returns:
            관련도 점수 (0.0 ~ 100.0)
        """
        if not title and not description:
            return 0.0

        matches, matched_keywords = self._calculate_match_internal(title, description)

        if not matches:
            return 0.0

        # 가중 점수 계산
        raw_score = 0.0
        for match in matches:
            # 빈도 보너스: log 스케일로 최대 2배까지
            frequency_bonus = min(1.0 + (match.frequency - 1) * 0.3, 2.0)
            raw_score += match.weight * frequency_bonus

        # 0~100 범위로 정규화 (보너스 적용 전에 정규화)
        # 최대 예상 점수: 모든 키워드가 제목+내용에서 매칭 (키워드 수 × 4.0 × 2.0)
        max_possible = len(self.keywords) * (self.TITLE_WEIGHT + self.DESCRIPTION_WEIGHT) * 2.0
        if max_possible == 0:
            return 0.0

        normalized_score = (raw_score / max_possible) * 100.0

        # 매칭된 키워드 수에 따른 보너스 계산 (정규화 후 적용하되 100을 초과하지 않도록)
        num_matched = len(matched_keywords)
        if num_matched >= 2:
            multi_bonus = self.MULTI_KEYWORD_BONUS ** (num_matched - 1)
            normalized_score = min(normalized_score * multi_bonus, 100.0)

        # 0~100 범위로 클리핑
        return round(min(max(normalized_score, 0.0), 100.0), 1)

    def filter_bids(self, bids: list[dict], min_score: float = 40.0) -> list[dict]:
        """
        관련도 점수가 임계값 이상인 공고만 필터링합니다.

        각 공고 dict에 'relevance_score' 필드를 추가하고,
        점수 내림차순으로 정렬하여 반환합니다.

        Args:
            bids: 공고 목록 (각 공고는 dict, 'title'과 'description' 키 필요)
            min_score: 최소 관련도 점수 (기본값: 40)

        Returns:
            필터링되고 정렬된 공고 목록 (관련도 점수가 추가됨)
        """
        scored_bids = []

        for bid in bids:
            title = bid.get('title', bid.get('bidNtceNm', ''))
            description = bid.get('description', '')

            score = self.calculate_relevance(title, description)
            if score >= min_score:
                # 원본 dict를 복사하여 점수를 추가
                scored_bid = {**bid, 'relevance_score': score}
                scored_bids.append(scored_bid)

        # 관련도 점수 내림차순 정렬
        scored_bids.sort(key=lambda x: x['relevance_score'], reverse=True)

        return scored_bids

    def get_match_details(self, title: str, description: str = '') -> list[MatchResult]:
        """
        키워드 매칭의 상세 결과를 반환합니다.
        디버깅이나 상세 보고서 생성 시 활용합니다.

        Args:
            title: 공고 제목
            description: 공고 내용

        Returns:
            매칭 결과 리스트
        """
        matches, _ = self._calculate_match_internal(title, description)
        return matches
