"""
RFP 비교 분석 모듈

두 개의 RFP(제안요청서) 텍스트를 비교하여 변경사항을
구조화된 형식으로 제공합니다.

Python 표준 라이브러리의 difflib만 사용하므로
외부 의존성이 없습니다.
"""

import difflib
import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)


class RFPDiffer:
    """
    RFP 비교 분석 클래스

    두 개의 RFP 텍스트를 비교하여 통합 diff,
    추가/삭제된 라인, 주요 변경사항 요약을 제공합니다.

    사용 예:
        differ = RFPDiffer()
        result = differ.compute_diff(old_rfp, new_rfp)
        changes = differ.extract_key_changes(old_rfp, new_rfp)
    """

    def __init__(self) -> None:
        """RFPDiffer를 초기화합니다."""
        logger.debug("RFPDiffer 초기화 완료")

    def compute_diff(self, old_text: str, new_text: str) -> dict:
        """
        두 RFP 텍스트의 차이를 분석합니다.

        Args:
            old_text: 이전 RFP 텍스트
            new_text: 새로운 RFP 텍스트

        Returns:
            분석 결과 딕셔너리:
            - unified_diff: 통합 diff 문자열
            - added_lines: 추가된 라인 리스트
            - removed_lines: 삭제된 라인 리스트
            - changed_count: 변경된 총 라인 수
            - similarity_ratio: 유사도 비율 (0.0~1.0)
        """
        # 빈 입력 처리
        old_text = old_text or ""
        new_text = new_text or ""

        old_lines = old_text.splitlines(keepends=True)
        new_lines = new_text.splitlines(keepends=True)

        # 통합 diff 생성
        unified = list(difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile="이전_RFP",
            tofile="새_RFP",
            lineterm="",
        ))
        unified_diff_str = "\n".join(unified)

        # 추가/삭제된 라인 분류
        added_lines: list[str] = []
        removed_lines: list[str] = []

        for line in unified:
            # diff 헤더 라인(---, +++, @@)은 제외
            if line.startswith("---") or line.startswith("+++") or line.startswith("@@"):
                continue
            if line.startswith("+"):
                content = line[1:].strip()
                if content:
                    added_lines.append(content)
            elif line.startswith("-"):
                content = line[1:].strip()
                if content:
                    removed_lines.append(content)

        # 유사도 비율 계산
        matcher = difflib.SequenceMatcher(None, old_text, new_text)
        similarity_ratio = round(matcher.ratio(), 4)

        # 변경 라인 수 합산
        changed_count = len(added_lines) + len(removed_lines)

        result = {
            "unified_diff": unified_diff_str,
            "added_lines": added_lines,
            "removed_lines": removed_lines,
            "changed_count": changed_count,
            "similarity_ratio": similarity_ratio,
        }

        logger.info(
            "RFP 비교 완료: 유사도=%.2f%%, 변경 %d건 (추가 %d, 삭제 %d)",
            similarity_ratio * 100,
            changed_count,
            len(added_lines),
            len(removed_lines),
        )
        return result

    def extract_key_changes(
        self, old_text: str, new_text: str
    ) -> list[dict]:
        """
        두 RFP 텍스트에서 주요 변경사항을 구조화하여 추출합니다.

        각 변경사항에 대해 유형(added/removed/modified),
        내용, 주변 컨텍스트를 제공합니다.

        Args:
            old_text: 이전 RFP 텍스트
            new_text: 새로운 RFP 텍스트

        Returns:
            변경사항 리스트. 각 항목:
            - type: 'added' | 'removed' | 'modified'
            - content: 변경된 내용
            - context: 변경 위치 주변의 컨텍스트 텍스트
        """
        old_text = old_text or ""
        new_text = new_text or ""

        old_lines = old_text.splitlines()
        new_lines = new_text.splitlines()

        changes: list[dict] = []

        # SequenceMatcher로 블록 단위 비교
        matcher = difflib.SequenceMatcher(None, old_lines, new_lines)

        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal":
                # 동일한 블록은 건너뜀
                continue

            # 컨텍스트: 변경 위치 앞뒤 2줄
            context_lines = self._get_context(old_lines, new_lines, i1, i2, j1, j2)
            context = "\n".join(context_lines)

            if tag == "insert":
                # 새로 추가된 라인들
                added_content = "\n".join(new_lines[j1:j2])
                if added_content.strip():
                    changes.append({
                        "type": "added",
                        "content": added_content,
                        "context": context,
                    })

            elif tag == "delete":
                # 삭제된 라인들
                removed_content = "\n".join(old_lines[i1:i2])
                if removed_content.strip():
                    changes.append({
                        "type": "removed",
                        "content": removed_content,
                        "context": context,
                    })

            elif tag == "replace":
                # 수정된 라인들 (이전 → 이후)
                old_content = "\n".join(old_lines[i1:i2])
                new_content = "\n".join(new_lines[j1:j2])
                if old_content.strip() or new_content.strip():
                    changes.append({
                        "type": "modified",
                        "content": f"[이전]\n{old_content}\n[이후]\n{new_content}",
                        "context": context,
                    })

        logger.info(
            "주요 변경사항 추출 완료: %d건 (추가 %d, 삭제 %d, 수정 %d)",
            len(changes),
            sum(1 for c in changes if c["type"] == "added"),
            sum(1 for c in changes if c["type"] == "removed"),
            sum(1 for c in changes if c["type"] == "modified"),
        )
        return changes

    @staticmethod
    def _get_context(
        old_lines: list[str],
        new_lines: list[str],
        i1: int,
        i2: int,
        j1: int,
        j2: int,
        context_size: int = 2,
    ) -> list[str]:
        """
        변경 위치 앞뒤의 컨텍스트 라인을 가져옵니다.

        Args:
            old_lines: 이전 텍스트 라인 리스트
            new_lines: 새 텍스트 라인 리스트
            i1, i2: 이전 텍스트에서 변경 범위
            j1, j2: 새 텍스트에서 변경 범위
            context_size: 앞뒤로 가져올 라인 수 (기본 2)

        Returns:
            컨텍스트 라인 리스트
        """
        context = []

        # 변경 위치 앞의 컨텍스트 (이전 텍스트 기준)
        start = max(0, i1 - context_size)
        for line in old_lines[start:i1]:
            context.append(f"  {line}")

        # 변경 내용 표시
        for line in old_lines[i1:i2]:
            context.append(f"- {line}")
        for line in new_lines[j1:j2]:
            context.append(f"+ {line}")

        # 변경 위치 뒤의 컨텍스트 (새 텍스트 기준)
        end = min(len(new_lines), j2 + context_size)
        for line in new_lines[j2:end]:
            context.append(f"  {line}")

        return context

    def find_similar_past_bid(
        self,
        db,
        current_bid: dict,
    ) -> Optional[dict]:
        """
        데이터베이스에서 현재 입찰공고와 유사한 과거 입찰을 검색합니다.

        입찰공고 제목에서 핵심 키워드를 추출하여
        과거 낙찰정보를 검색합니다.

        Args:
            db: DatabaseManager 인스턴스
            current_bid: 현재 입찰공고 딕셔너리
                        (title, bid_ntce_no 등의 키 포함)

        Returns:
            가장 유사한 과거 입찰 딕셔너리 또는 None.
            반환 항목: bid_title, winner_name, award_amount,
                      award_date, similarity
        """
        title = current_bid.get("title", "")
        if not title:
            logger.warning("입찰공고 제목이 비어있어 유사 입찰을 검색할 수 없습니다.")
            return None

        # 제목에서 핵심 키워드 추출 (2글자 이상 단어만)
        keywords = self._extract_title_keywords(title)
        if not keywords:
            logger.debug("제목에서 키워드를 추출할 수 없습니다: %s", title)
            return None

        try:
            # DatabaseManager 임포트 (순환 참조 방지를 위해 여기서 임포트)
            from src.models.database import DatabaseManager

            # db 인스턴스 타입 검증
            if not isinstance(db, DatabaseManager):
                logger.warning("유효하지 않은 DatabaseManager 인스턴스입니다.")
                return None

            # 각 키워드로 낙찰정보 검색
            best_match: Optional[dict] = None
            best_similarity = 0.0

            for keyword in keywords:
                awards = db.get_awards_by_title(keyword, limit=10)

                for award in awards:
                    # 현재 공고와 동일한 번호는 제외
                    current_bid_no = current_bid.get("bid_ntce_no", "")
                    if award.bid_ntce_no == current_bid_no:
                        continue

                    # 제목 유사도 계산
                    similarity = difflib.SequenceMatcher(
                        None, title, award.bid_title
                    ).ratio()

                    if similarity > best_similarity:
                        best_similarity = similarity
                        best_match = {
                            "bid_ntce_no": award.bid_ntce_no,
                            "bid_title": award.bid_title,
                            "winner_name": award.winner_name,
                            "award_amount": award.award_amount,
                            "award_date": award.award_date,
                            "similarity": round(similarity, 4),
                        }

            if best_match:
                logger.info(
                    "유사 과거 입찰 발견: '%s' (유사도: %.2f%%)",
                    best_match["bid_title"],
                    best_match["similarity"] * 100,
                )
            else:
                logger.debug("유사한 과거 입찰을 찾지 못했습니다: %s", title)

            return best_match

        except ImportError:
            logger.error(
                "src.models.database 모듈을 임포트할 수 없습니다. "
                "유사 입찰 검색을 건너뜁니다."
            )
            return None
        except Exception as e:
            logger.error("유사 과거 입찰 검색 중 오류 발생: %s", e)
            return None

    @staticmethod
    def _extract_title_keywords(title: str) -> list[str]:
        """
        입찰공고 제목에서 검색용 핵심 키워드를 추출합니다.

        불용어(조사, 접속사 등)를 제거하고 2글자 이상의
        의미 있는 단어만 반환합니다.

        Args:
            title: 입찰공고 제목

        Returns:
            핵심 키워드 리스트 (최대 5개)
        """
        # 불용어 목록 (한국어 조사, 접속사, 일반적인 행정 용어)
        stopwords = {
            "및", "의", "에", "를", "을", "이", "가", "은", "는",
            "한", "로", "으로", "에서", "까지", "부터", "대한",
            "위한", "관한", "따른", "등", "외", "건", "차",
            "용역", "사업", "구매", "조달", "계약", "입찰",
            "공고", "제안", "요청", "수행", "추진",
        }

        # 특수문자 제거, 단어 분리
        cleaned = re.sub(r"[^\w\s가-힣]", " ", title)
        words = cleaned.split()

        # 불용어 제거 및 2글자 이상 필터링
        keywords = [
            w for w in words
            if len(w) >= 2 and w not in stopwords
        ]

        # 중복 제거 후 최대 5개 반환
        seen: set[str] = set()
        unique_keywords: list[str] = []
        for kw in keywords:
            if kw not in seen:
                seen.add(kw)
                unique_keywords.append(kw)
            if len(unique_keywords) >= 5:
                break

        return unique_keywords
