"""
벡터 저장소 모듈

ChromaDB를 활용한 RAG(검색 증강 생성)용 벡터 저장소를 제공합니다.
입찰공고, 뉴스, 낙찰정보 등의 문서를 임베딩하여 저장하고,
유사 문서 검색 기능을 지원합니다.

chromadb가 설치되지 않은 환경에서는 간단한 키워드 매칭으로
폴백하여 동작합니다.
"""

import json
import logging
from pathlib import Path
from typing import Optional

from src.config import PROJECT_ROOT

logger = logging.getLogger(__name__)

# chromadb 선택적 임포트
try:
    import chromadb
    from chromadb.config import Settings

    CHROMADB_AVAILABLE = True
except ImportError:
    CHROMADB_AVAILABLE = False
    logger.warning(
        "chromadb 라이브러리가 설치되지 않았습니다. "
        "벡터 검색 대신 키워드 매칭을 사용합니다. "
        "'pip install chromadb'로 설치해 주세요."
    )

# 기본 벡터DB 저장 경로
DEFAULT_PERSIST_DIR = PROJECT_ROOT / "data" / "vectordb"

# 컬렉션 이름
COLLECTION_NAME = "nara_documents"


class VectorStore:
    """
    ChromaDB 기반 벡터 저장소 클래스

    입찰공고 RFP, 뉴스 기사, 낙찰정보 등의 텍스트 문서를
    벡터로 변환하여 저장하고, 유사 문서를 검색합니다.

    chromadb가 설치되지 않은 경우 간단한 키워드 기반
    폴백 검색을 제공합니다.

    사용 예:
        store = VectorStore()
        store.add_documents(
            texts=["입찰공고 내용..."],
            metadatas=[{"source_type": "bid", "bid_no": "20250001"}],
            ids=["bid_20250001"]
        )
        results = store.search("AI 플랫폼 개발")
    """

    def __init__(self, persist_dir: Optional[str] = None) -> None:
        """
        VectorStore를 초기화합니다.

        Args:
            persist_dir: ChromaDB 데이터 저장 디렉터리 경로.
                         None이면 기본 경로(data/vectordb) 사용.
        """
        self._persist_dir = Path(persist_dir) if persist_dir else DEFAULT_PERSIST_DIR

        # 경로 검증: '..' 포함 여부 확인 (디렉터리 트래버설 방지)
        if '..' in str(self._persist_dir):
            raise ValueError(
                f"persist_dir에 '..' 경로가 포함될 수 없습니다: {self._persist_dir}"
            )

        self._client = None
        self._collection = None

        # 폴백용 인메모리 저장소 (chromadb 미설치 시)
        self._fallback_docs: list[dict] = []

        if CHROMADB_AVAILABLE:
            self._init_chromadb()
        else:
            logger.info("폴백 모드로 VectorStore를 초기화합니다.")

    def _init_chromadb(self) -> None:
        """ChromaDB 클라이언트와 컬렉션을 초기화합니다."""
        try:
            # 저장 디렉터리 생성
            self._persist_dir.mkdir(parents=True, exist_ok=True)

            # 영구 저장소 클라이언트 생성
            self._client = chromadb.PersistentClient(
                path=str(self._persist_dir),
                settings=Settings(anonymized_telemetry=False),
            )

            # 컬렉션 생성 또는 가져오기
            self._collection = self._client.get_or_create_collection(
                name=COLLECTION_NAME,
                metadata={"description": "NARA 입찰분석 문서 저장소"},
            )

            doc_count = self._collection.count()
            logger.info(
                "ChromaDB 초기화 완료: %s (문서 수: %d)",
                self._persist_dir,
                doc_count,
            )
        except Exception as e:
            logger.error("ChromaDB 초기화 실패: %s. 폴백 모드로 전환합니다.", e)
            self._client = None
            self._collection = None

    @property
    def is_available(self) -> bool:
        """ChromaDB가 사용 가능한 상태인지 반환합니다."""
        return self._collection is not None

    # ──────────────────────────────────────────
    # 문서 추가
    # ──────────────────────────────────────────

    def add_documents(
        self,
        texts: list[str],
        metadatas: list[dict],
        ids: list[str],
    ) -> int:
        """
        문서를 벡터 저장소에 추가(upsert)합니다.

        Args:
            texts: 문서 텍스트 리스트
            metadatas: 각 문서의 메타데이터 딕셔너리 리스트
                       (source_type, bid_no, org_name 등)
            ids: 각 문서의 고유 ID 리스트

        Returns:
            추가된 문서 수
        """
        if not texts:
            return 0

        # 입력 길이 검증
        if not (len(texts) == len(metadatas) == len(ids)):
            logger.error(
                "texts(%d), metadatas(%d), ids(%d) 길이가 일치하지 않습니다.",
                len(texts), len(metadatas), len(ids),
            )
            return 0

        # 빈 텍스트 필터링
        valid_items = [
            (text, meta, doc_id)
            for text, meta, doc_id in zip(texts, metadatas, ids)
            if text and text.strip()
        ]

        if not valid_items:
            logger.warning("추가할 유효한 문서가 없습니다.")
            return 0

        valid_texts, valid_metas, valid_ids = zip(*valid_items)

        # 메타데이터 값을 ChromaDB 호환 타입으로 변환
        sanitized_metas = [self._sanitize_metadata(m) for m in valid_metas]

        if self.is_available:
            return self._add_to_chromadb(
                list(valid_texts), list(sanitized_metas), list(valid_ids)
            )
        else:
            return self._add_to_fallback(
                list(valid_texts), list(sanitized_metas), list(valid_ids)
            )

    def _sanitize_metadata(self, metadata: dict) -> dict:
        """
        메타데이터 값을 ChromaDB 호환 타입(str, int, float, bool)으로 변환합니다.

        Args:
            metadata: 원본 메타데이터

        Returns:
            변환된 메타데이터 딕셔너리
        """
        sanitized = {}
        for key, value in metadata.items():
            if value is None:
                sanitized[key] = ""
            elif isinstance(value, (str, int, float, bool)):
                sanitized[key] = value
            elif isinstance(value, (list, dict)):
                # 리스트/딕셔너리는 문자열로 변환
                sanitized[key] = json.dumps(value, ensure_ascii=False)
            else:
                sanitized[key] = str(value)
        return sanitized

    def _add_to_chromadb(
        self,
        texts: list[str],
        metadatas: list[dict],
        ids: list[str],
    ) -> int:
        """ChromaDB에 문서를 upsert합니다. 500건씩 배치 처리합니다."""
        try:
            batch_size = 500
            total_added = 0
            for i in range(0, len(texts), batch_size):
                batch_texts = texts[i:i + batch_size]
                batch_metas = metadatas[i:i + batch_size]
                batch_ids = ids[i:i + batch_size]
                self._collection.upsert(
                    documents=batch_texts,
                    metadatas=batch_metas,
                    ids=batch_ids,
                )
                total_added += len(batch_texts)
                if len(texts) > batch_size:
                    logger.debug(
                        "ChromaDB 배치 처리 중: %d/%d건 완료",
                        min(i + batch_size, len(texts)), len(texts)
                    )
            logger.info("ChromaDB에 문서 %d건 추가(upsert) 완료", total_added)
            return total_added
        except Exception as e:
            logger.error("ChromaDB 문서 추가 실패: %s", e)
            return 0

    def _add_to_fallback(
        self,
        texts: list[str],
        metadatas: list[dict],
        ids: list[str],
    ) -> int:
        """폴백 인메모리 저장소에 문서를 추가합니다."""
        added = 0
        for text, meta, doc_id in zip(texts, metadatas, ids):
            # 기존 ID가 있으면 업데이트
            existing = next(
                (d for d in self._fallback_docs if d["id"] == doc_id), None
            )
            if existing:
                existing["text"] = text
                existing["metadata"] = meta
            else:
                self._fallback_docs.append({
                    "id": doc_id,
                    "text": text,
                    "metadata": meta,
                })
            added += 1

        logger.info("폴백 저장소에 문서 %d건 추가 완료", added)
        return added

    # ──────────────────────────────────────────
    # 입찰 컨텍스트 일괄 추가
    # ──────────────────────────────────────────

    def add_bid_context(
        self,
        bid_no: str,
        rfp_text: str,
        news_articles: list[dict],
        past_awards: list[dict],
    ) -> int:
        """
        특정 입찰공고의 관련 컨텍스트를 일괄 추가합니다.

        RFP 텍스트, 관련 뉴스 기사, 과거 낙찰정보를 한 번에
        벡터 저장소에 저장합니다.

        Args:
            bid_no: 입찰공고번호
            rfp_text: RFP(제안요청서) 전문 텍스트
            news_articles: 관련 뉴스 기사 리스트
                          각 항목: {"title": str, "description": str, ...}
            past_awards: 과거 낙찰정보 리스트
                        각 항목: {"bid_title": str, "winner_name": str, ...}

        Returns:
            추가된 총 문서 수
        """
        texts: list[str] = []
        metadatas: list[dict] = []
        ids: list[str] = []

        # 1. RFP 텍스트 추가
        if rfp_text and rfp_text.strip():
            texts.append(rfp_text)
            metadatas.append({
                "source_type": "bid",
                "bid_no": bid_no,
                "content_type": "rfp",
            })
            ids.append(f"rfp_{bid_no}")

        # 2. 뉴스 기사 추가
        for idx, article in enumerate(news_articles or []):
            title = article.get("title", "")
            description = article.get("description", "")
            news_text = f"{title}\n{description}".strip()

            if news_text:
                texts.append(news_text)
                metadatas.append({
                    "source_type": "news",
                    "bid_no": bid_no,
                    "news_title": title,
                    "news_link": article.get("link", ""),
                })
                ids.append(f"news_{bid_no}_{idx}")

        # 3. 과거 낙찰정보 추가
        for idx, award in enumerate(past_awards or []):
            bid_title = award.get("bid_title", "")
            winner = award.get("winner_name", "")
            amount = award.get("award_amount", "")
            award_text = f"낙찰: {bid_title} | 낙찰자: {winner} | 금액: {amount}"

            if bid_title:
                texts.append(award_text)
                metadatas.append({
                    "source_type": "award",
                    "bid_no": bid_no,
                    "award_bid_title": bid_title,
                    "winner_name": winner,
                })
                ids.append(f"award_{bid_no}_{idx}")

        if not texts:
            logger.warning("입찰 %s: 추가할 컨텍스트 문서가 없습니다.", bid_no)
            return 0

        return self.add_documents(texts, metadatas, ids)

    # ──────────────────────────────────────────
    # 검색
    # ──────────────────────────────────────────

    def search(
        self,
        query: str,
        n_results: int = 5,
        where: Optional[dict] = None,
    ) -> list[dict]:
        """
        유사 문서를 검색합니다.

        Args:
            query: 검색 쿼리 텍스트
            n_results: 반환할 최대 결과 수 (기본 5)
            where: ChromaDB 필터 조건 딕셔너리
                   예: {"source_type": "bid"}

        Returns:
            검색 결과 리스트. 각 항목은 다음 키를 포함:
            - text: 문서 텍스트
            - metadata: 메타데이터 딕셔너리
            - distance: 유사도 거리 (낮을수록 유사)
        """
        if not query or not query.strip():
            return []

        if self.is_available:
            return self._search_chromadb(query, n_results, where)
        else:
            return self._search_fallback(query, n_results, where)

    def _search_chromadb(
        self,
        query: str,
        n_results: int,
        where: Optional[dict],
    ) -> list[dict]:
        """ChromaDB에서 유사 문서를 검색합니다."""
        try:
            # 컬렉션 내 문서 수 확인 (n_results가 문서 수보다 클 수 없음)
            total = self._collection.count()
            if total == 0:
                return []

            effective_n = min(n_results, total)

            query_params = {
                "query_texts": [query],
                "n_results": effective_n,
            }
            if where:
                query_params["where"] = where

            results = self._collection.query(**query_params)

            # 결과를 평탄화하여 반환
            output = []
            if results and results["documents"]:
                documents = results["documents"][0]
                metadatas = results["metadatas"][0] if results["metadatas"] else [{}] * len(documents)
                distances = results["distances"][0] if results["distances"] else [0.0] * len(documents)

                for doc, meta, dist in zip(documents, metadatas, distances):
                    output.append({
                        "text": doc,
                        "metadata": meta,
                        "distance": dist,
                    })

            logger.debug("ChromaDB 검색 완료: 쿼리='%s', 결과 %d건", query[:50], len(output))
            return output

        except Exception as e:
            logger.error("ChromaDB 검색 실패: %s", e)
            return []

    def _search_fallback(
        self,
        query: str,
        n_results: int,
        where: Optional[dict],
    ) -> list[dict]:
        """
        폴백 키워드 매칭 검색을 수행합니다.

        쿼리를 단어로 분리한 뒤, 각 문서에서 일치하는
        단어 비율을 점수로 사용합니다.
        """
        if not self._fallback_docs:
            return []

        query_words = set(query.lower().split())
        if not query_words:
            return []

        scored: list[tuple[float, dict]] = []

        for doc in self._fallback_docs:
            # where 필터 적용
            if where:
                match = all(
                    doc["metadata"].get(k) == v
                    for k, v in where.items()
                )
                if not match:
                    continue

            # 키워드 매칭 점수 계산
            doc_words = set(doc["text"].lower().split())
            common = query_words & doc_words
            if common:
                # 일치 비율을 거리로 변환 (0에 가까울수록 유사)
                score = 1.0 - (len(common) / len(query_words))
                scored.append((score, doc))

        # 거리순 정렬 (낮을수록 유사)
        scored.sort(key=lambda x: x[0])

        results = []
        for distance, doc in scored[:n_results]:
            results.append({
                "text": doc["text"],
                "metadata": doc["metadata"],
                "distance": distance,
            })

        logger.debug(
            "폴백 검색 완료: 쿼리='%s', 결과 %d건", query[:50], len(results)
        )
        return results

    def search_for_bid(
        self,
        bid_title: str,
        org_name: str,
        n_results: int = 5,
    ) -> list[dict]:
        """
        특정 입찰공고와 관련된 컨텍스트를 검색합니다.

        입찰공고 제목과 발주기관명을 결합하여 검색 쿼리를 구성합니다.

        Args:
            bid_title: 입찰공고 제목
            org_name: 발주기관명
            n_results: 반환할 최대 결과 수 (기본 5)

        Returns:
            검색 결과 리스트 (search 메서드와 동일한 형식)
        """
        query = f"{bid_title} {org_name}".strip()
        if not query:
            logger.warning("검색 쿼리가 비어있습니다. (제목과 기관명 모두 공백)")
            return []

        return self.search(query=query, n_results=n_results)

    # ──────────────────────────────────────────
    # 통계 및 관리
    # ──────────────────────────────────────────

    def get_collection_stats(self) -> dict:
        """
        벡터 저장소의 통계 정보를 반환합니다.

        Returns:
            통계 딕셔너리:
            - total_documents: 총 문서 수
            - persist_dir: 저장 경로
            - backend: 사용 중인 백엔드 ("chromadb" 또는 "fallback")
            - collection_name: 컬렉션 이름
        """
        stats = {
            "persist_dir": str(self._persist_dir),
            "collection_name": COLLECTION_NAME,
        }

        if self.is_available:
            try:
                stats["total_documents"] = self._collection.count()
                stats["backend"] = "chromadb"
            except Exception as e:
                logger.error("컬렉션 통계 조회 실패: %s", e)
                stats["total_documents"] = -1
                stats["backend"] = "chromadb (오류)"
        else:
            stats["total_documents"] = len(self._fallback_docs)
            stats["backend"] = "fallback"

        return stats

    def clear(self) -> None:
        """
        벡터 저장소의 모든 문서를 삭제합니다.

        주의: 이 작업은 되돌릴 수 없습니다.
        """
        if self.is_available:
            try:
                # 컬렉션을 삭제 후 재생성
                self._client.delete_collection(COLLECTION_NAME)
                self._collection = self._client.get_or_create_collection(
                    name=COLLECTION_NAME,
                    metadata={"description": "NARA 입찰분석 문서 저장소"},
                )
                logger.info("ChromaDB 컬렉션 초기화 완료: %s", COLLECTION_NAME)
            except Exception as e:
                logger.error("ChromaDB 컬렉션 초기화 실패: %s", e)
        else:
            count = len(self._fallback_docs)
            self._fallback_docs.clear()
            logger.info("폴백 저장소 초기화 완료: %d건 삭제", count)

    def delete_by_ids(self, ids: list[str]) -> int:
        """
        ID 목록으로 문서를 삭제합니다.

        Args:
            ids: 삭제할 문서 ID 리스트

        Returns:
            삭제된 문서 수
        """
        if not ids:
            return 0

        if self.is_available:
            try:
                self._collection.delete(ids=ids)
                logger.info("ChromaDB에서 문서 %d건 삭제 완료", len(ids))
                return len(ids)
            except Exception as e:
                logger.error("ChromaDB 문서 삭제 실패: %s", e)
                return 0
        else:
            ids_set = set(ids)
            before_count = len(self._fallback_docs)
            self._fallback_docs = [
                doc for doc in self._fallback_docs
                if doc["id"] not in ids_set
            ]
            deleted = before_count - len(self._fallback_docs)
            logger.info("폴백 저장소에서 문서 %d건 삭제 완료", deleted)
            return deleted

    @staticmethod
    def _chunk_text(text: str, max_chars: int = 2000, overlap: int = 200) -> list[str]:
        """
        긴 텍스트를 지정된 크기로 분할합니다.

        각 청크는 max_chars 이하이며, overlap 문자만큼
        이전 청크와 겹칩됩니다.

        Args:
            text: 분할할 텍스트
            max_chars: 청크당 최대 문자 수 (기본 2000)
            overlap: 청크 간 겹침 문자 수 (기본 200)

        Returns:
            텍스트 청크 리스트
        """
        if not text:
            return []
        if len(text) <= max_chars:
            return [text]

        chunks = []
        start = 0
        while start < len(text):
            end = start + max_chars
            chunk = text[start:end]
            chunks.append(chunk)
            # 다음 청크 시작점: 겹침을 고려하여 이동
            start = end - overlap
            # 마지막 청크가 너무 작으면 종료
            if start + overlap >= len(text):
                break

        return chunks
