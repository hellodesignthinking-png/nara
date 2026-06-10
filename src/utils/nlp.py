"""
공통 NLP 유틸리티 모듈

프로젝트 전반에서 사용되는 불용어 목록, 유사어 사전,
키워드 추출 및 유사어 매칭 기능을 제공합니다.

통합 소스:
- src/analyzers/keyword_filter.py  (유사어 사전)
- src/analyzers/biz_matcher.py     (업종 유사어 + 불용어)
- src/analyzers/rfp_differ.py      (불용어 + 키워드 추출)
"""

import re


# ──────────────────────────────────────────────
# 불용어 통합 (biz_matcher + rfp_differ 합집합)
# ──────────────────────────────────────────────
STOPWORDS: set[str] = {
    # 한국어 조사 / 접속사 (rfp_differ 기원)
    '및', '의', '에', '를', '을', '이', '가', '은', '는',
    '한', '로', '으로', '에서', '까지', '부터',
    # 관계·목적 표현 (biz_matcher + rfp_differ 공통)
    '대한', '위한', '관한', '따른', '통한',
    # 일반 행정/조달 용어 (rfp_differ 기원)
    '용역', '사업', '구매', '조달', '계약', '입찰',
    '공고', '제안', '요청',
    # 동작·계획 (biz_matcher + rfp_differ 공통)
    '수행', '추진', '계획', '방안', '연구',
    # 범용 수식어 (biz_matcher 기원)
    '서비스', '기반', '관련', '활용',
    # 기타 (rfp_differ 기원)
    '등', '외', '건', '차',
}


# ──────────────────────────────────────────────
# 유사어 그룹 통합 (keyword_filter + biz_matcher)
#
# 각 그룹의 대표어(키)와 유사어 리스트(값)로 구성.
# keyword_filter의 list 기반 그룹과 biz_matcher의
# set 기반 그룹을 병합하여 중복을 제거하였습니다.
# ──────────────────────────────────────────────
SYNONYM_GROUPS: dict[str, list[str]] = {
    # keyword_filter: AI 그룹 + biz_matcher: AI_DATA 그룹
    'AI': [
        'AI', '인공지능', '머신러닝', '딥러닝', 'ML', 'DL', '기계학습',
        '데이터', '빅데이터', '데이터분석', '데이터베이스', 'DB', 'DW',
        '데이터사이언스', '자연어처리', 'NLP', '컴퓨터비전',
    ],
    # keyword_filter: SW개발 그룹 + biz_matcher: IT_SW 그룹
    'SW개발': [
        'SW개발', '소프트웨어', 'IT', '정보시스템', 'SI', '시스템통합', '프로그램',
        '프로그램개발', '소프트웨어개발', '정보기술', '응용SW', '시스템SW',
        '솔루션', '웹개발', '앱개발', '모바일개발',
    ],
    # keyword_filter: 클라우드 그룹 + biz_matcher: CLOUD_INFRA 그룹
    '클라우드': [
        '클라우드', 'IaaS', 'SaaS', 'PaaS', 'AWS', 'Azure',
        '인프라', 'IDC', '서버', '네트워크', '정보통신', '통신',
    ],
    # keyword_filter: 보안 그룹 + biz_matcher: SECURITY 그룹
    '보안': [
        '보안', '정보보안', '사이버보안', 'ISMS', '개인정보',
        '개인정보보호', '보안관제', '취약점진단', '암호화',
    ],
    # keyword_filter: 컨설팅 그룹 + biz_matcher: CONSULTING 그룹
    '컨설팅': [
        '컨설팅', '자문', '용역', '연구용역', '정책연구',
        'ISP', 'ISMP', 'BPR', '전략수립', '기획',
    ],
    # keyword_filter: 마케팅 그룹 + biz_matcher: MARKETING 그룹
    '마케팅': [
        '마케팅', '홍보', '광고', '브랜딩', 'PR', '캠페인',
        '디자인', '콘텐츠', '미디어', '영상제작',
    ],
    # keyword_filter 전용: 플랫폼 그룹
    '플랫폼': [
        '플랫폼', '포털', '시스템구축', '웹사이트',
    ],
    # biz_matcher 전용: CONSTRUCTION 그룹
    '건설': [
        '건설', '토목', '건축', '시설물', '전기공사', '기계설비',
        '소방', '조경',
    ],
}

# 역방향 인덱스: 개별 단어 → 그룹 대표어 (빠른 조회용)
_WORD_TO_GROUP: dict[str, str] = {}
for _group_name, _words in SYNONYM_GROUPS.items():
    for _word in _words:
        _WORD_TO_GROUP[_word.upper()] = _group_name


# ──────────────────────────────────────────────
# 공개 함수
# ──────────────────────────────────────────────

def extract_keywords(text: str, min_length: int = 2) -> list[str]:
    """
    텍스트에서 불용어를 제거하고 의미 있는 키워드를 추출합니다.

    한글 2글자 이상, 영문 2글자 이상의 단어를 추출한 뒤
    STOPWORDS에 해당하는 단어를 제거합니다.
    중복을 제거하되 원래 등장 순서를 유지합니다.

    Args:
        text: 키워드를 추출할 원본 텍스트
        min_length: 최소 단어 길이 (기본값 2)

    Returns:
        추출된 키워드 리스트 (중복 제거, 등장 순서 유지)
    """
    if not text:
        return []

    # 한글·영문 단어 추출
    words = re.findall(r'[가-힣]{2,}|[A-Za-z0-9]{2,}|[A-Za-z]+\d+[A-Za-z0-9]*|\d+[A-Za-z]+[A-Za-z0-9]*', text)

    seen: set[str] = set()
    keywords: list[str] = []

    for word in words:
        if len(word) < min_length:
            continue
        if word in STOPWORDS:
            continue
        if word not in seen:
            seen.add(word)
            keywords.append(word)

    return keywords


def find_synonyms(keyword: str) -> list[str]:
    """
    주어진 키워드가 속한 유사어 그룹의 모든 유사어를 반환합니다.

    키워드가 어떤 유사어 그룹에도 속하지 않으면 빈 리스트를 반환합니다.
    반환 리스트에는 입력 키워드 자신도 포함됩니다.

    Args:
        keyword: 유사어를 조회할 키워드

    Returns:
        유사어 리스트 (해당 그룹 전체). 그룹이 없으면 빈 리스트.
    """
    if not keyword:
        return []

    group_name = _WORD_TO_GROUP.get(keyword.upper())
    if group_name is None:
        return []

    return list(SYNONYM_GROUPS[group_name])


def is_synonym_match(word1: str, word2: str) -> bool:
    """
    두 단어가 같은 유사어 그룹에 속하는지 판단합니다.

    대소문자를 무시하여 비교합니다.
    두 단어가 동일한 경우에도 True를 반환합니다.

    Args:
        word1: 비교할 첫 번째 단어
        word2: 비교할 두 번째 단어

    Returns:
        두 단어가 같은 유사어 그룹에 속하면 True, 아니면 False
    """
    if not word1 or not word2:
        return False

    # 동일 단어 (대소문자 무시)
    if word1.upper() == word2.upper():
        return True

    group1 = _WORD_TO_GROUP.get(word1.upper())
    group2 = _WORD_TO_GROUP.get(word2.upper())

    if group1 is None or group2 is None:
        return False

    return group1 == group2
