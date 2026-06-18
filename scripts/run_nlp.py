#!/usr/bin/env python3
"""
지자체 정책 및 뉴스 자연어 처리(NLP) 분석엔진 시뮬레이터 (NLP Analysis Engine)
수집된 텍스트에서 주요 키워드를 추출하고, TF-IDF 기반의 요약 알고리즘을 사용해 AI 3줄 요약을 자동 생성합니다.
"""

import os
import re
import json
import sqlite3
from collections import Counter
import math
import logging
from typing import List, Dict, Tuple

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("NLP-Engine")

# 한국어 불용어 리스트 (분석에서 제외할 의미 없는 단어들)
STOPWORDS = {
    "본", "및", "이", "그", "저", "하는", "를", "을", "에", "의", "와", "과", "으로", 
    "로", "에서", "합니다", "있습니다", "위한", "대한", "통해", "의한", "등을", 
    "등의", "관련", "사업", "공고", "모집", "지원", "계획", "분야", "전문", "실시"
}

def clean_text(text: str) -> str:
    """텍스트에서 특수기호를 제거하고 공백을 정제합니다."""
    text = re.sub(r"[^\w\s\.]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()

def tokenize(text: str) -> List[str]:
    """의존성 없는 정규식 형태의 한국어 명사 추출 시뮬레이터 (어절 단어 분절)"""
    cleaned = clean_text(text)
    words = cleaned.split()
    
    # 2글자 이상이며 불용어가 아닌 단어 추출
    tokens = []
    for word in words:
        # 조사 제거 (간단 래핑)
        for suffix in ["입니다", "합니다", "에서는", "을", "를", "이", "가", "은", "는", "에", "의", "로", "으로", "과", "와"]:
            if word.endswith(suffix) and len(word) > len(suffix):
                word = word[:-len(suffix)]
                break
        
        # 특수 클렌징 후 최종 필터링
        word = re.sub(r"\.$", "", word)  # 마침표 제거
        if len(word) >= 2 and word not in STOPWORDS:
            tokens.append(word)
            
    return tokens

class NLPEngine:
    """자연어 처리 기반 지자체 정책 분석 및 요약 엔진"""
    def __init__(self, db_path: str = "data/nara.db"):
        self.db_path = db_path
        if not os.path.exists(db_path):
            raise FileNotFoundError(f"Database not found at '{db_path}'. Please run 'collect_policies.py' first.")

    def run_analysis(self) -> List[Dict]:
        """모든 정책 데이터를 순회하며 분석을 수행합니다."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM municipal_policies")
        rows = cursor.fetchall()

        analyzed_results = []
        logger.info(f"Loaded {len(rows)} policies for NLP processing.")

        for row in rows:
            content = row["content"]
            title = row["title"]
            region = row["region"]
            
            # 1. 토큰화 및 키워드 추출
            tokens = tokenize(title + " " + content)
            keyword_counts = Counter(tokens)
            top_keywords = [item[0] for item in keyword_counts.most_common(5)]

            # 2. TF-IDF 가중치 기반 문장 요약 (TextRank 유사 알고리즘)
            summary = self.summarize_sentences(content, tokens)

            # 3. AI 연관성 점수 계산 (예: 기업의 주요 관심 키워드인 '스마트', '디지털', 'AI', '창업'과 매칭)
            ai_score = self.calculate_relevance_score(tokens)

            analyzed_results.append({
                "id": row["id"],
                "region": region,
                "title": title,
                "budget": row["budget"],
                "keywords": top_keywords,
                "ai_summary": summary,
                "relevance_score": ai_score
            })
            
        conn.close()
        return analyzed_results

    def summarize_sentences(self, text: str, all_tokens: List[str], num_sentences: int = 2) -> str:
        """가중치 기반 핵심 문장 추출을 통한 2-3줄 요약 알고리즘"""
        sentences = [s.strip() for s in text.split(".") if s.strip()]
        if len(sentences) <= num_sentences:
            return " · ".join(sentences)

        # 단어 빈도수 사전
        freq_dict = Counter(all_tokens)
        
        # 문장별 중요도 점수 합산
        sentence_scores = {}
        for i, sentence in enumerate(sentences):
            sentence_tokens = tokenize(sentence)
            score = sum(freq_dict.get(token, 0) for token in sentence_tokens)
            
            # 첫 번째 문장에 대한 가중치 부여 (보통 두괄식이 많음)
            if i == 0:
                score *= 1.2
                
            sentence_scores[i] = score

        # 점수가 가장 높은 상위 N개의 문장 정렬 후 병합
        top_sentence_indices = sorted(sentence_scores, key=sentence_scores.get, reverse=True)[:num_sentences]
        top_sentence_indices.sort()  # 원래 글의 순서대로 출력하기 위함

        summary_list = [sentences[idx] for idx in top_sentence_indices]
        return " · ".join(summary_list) + "."

    def calculate_relevance_score(self, tokens: List[str]) -> float:
        """핵심 전략 분야 키워드가 포함되었는지 확인하고 점수를 환산 (100점 만점)"""
        target_keywords = {
            "스마트": 25, "디지털": 25, "AI": 30, "인공지능": 30, 
            "플랫폼": 20, "창업": 15, "실증": 15, "교통": 10, "가상": 15
        }
        score = 0.0
        seen = set()
        for token in tokens:
            for kw, val in target_keywords.items():
                if kw in token and kw not in seen:
                    score += val
                    seen.add(kw)
        return min(score, 100.0)

def display_report(results: List[Dict]):
    """분석 결과를 콘솔에 가독성 높게 출력"""
    logger.info("=== 지자체 정책 자연어 처리(NLP) 분석 보고서 ===")
    
    # 5개 샘플만 보기 좋게 출력
    for r in results[:5]:
        print("-" * 60)
        print(f"[{r['region']}] {r['title']}")
        print(f"💰 예산규모: {r['budget']:,}원")
        print(f"🏷️ 핵심 키워드: {', '.join(r['keywords'])}")
        print(f"🤖 AI 핵심 요약: {r['ai_summary']}")
        print(f"⚡ 연관성 및 사업추천 지수: {r['relevance_score']}점")
    
    print("-" * 60)
    logger.info(f"Report generated successfully. Analyzed {len(results)} municipal policies.")

if __name__ == "__main__":
    try:
        engine = NLPEngine()
        results = engine.run_analysis()
        display_report(results)
        
        # 통합 DB 업데이트 적용
        logger.info("Updating NLP analysis results back to database...")
        conn = sqlite3.connect(engine.db_path)
        with conn:
            for r in results:
                keywords_json = json.dumps(r["keywords"], ensure_ascii=False)
                conn.execute(
                    "UPDATE municipal_policies SET keywords = ?, ai_summary = ?, relevance_score = ? WHERE id = ?",
                    (keywords_json, r["ai_summary"], r["relevance_score"], r["id"])
                )
        logger.info(f"Successfully updated {len(results)} records in database.")
    except FileNotFoundError as e:
        logger.error(e)
        print("\n[안내] 먼저 'python scripts/collect_policies.py'를 실행하여 모의 수집을 완료해주세요.\n")
