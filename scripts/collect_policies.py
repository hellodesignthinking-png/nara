#!/usr/bin/env python3
"""
지자체 정책 및 뉴스 데이터 수집 시뮬레이터 (Policy Collector Simulator)
전국의 지자체 고시공고 및 관련 뉴스를 크롤링하여 저장하는 아키텍처 예제입니다.
"""

import os
import sys
import json
import sqlite3
import datetime
import logging
from typing import List, Dict

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("PolicyCollector")

# 모의 수집할 전국 지자체 리스트
MUNICIPALITIES = [
    "서울특별시", "부산광역시", "경기도", "인천광역시", "경상남도", 
    "경상북도", "충청남도", "충청북도", "전라남도", "전북특별자치도",
    "제주특별자치도", "강원특별자치도", "대전광역시", "대구광역시"
]

# 모의 정책 수집 소스 템플릿
POLICY_TEMPLATES = [
    {
        "title": "{city} 스마트시티 지능형 교통망(ITS) 고도화 사업 공고",
        "category": "ICT/교통",
        "department": "도시교통실",
        "budget": 2400000000,
        "content": "본 사업은 {city} 관내 지능형 교통 센서 및 실시간 교통 통제 AI 알고리즘을 도입하여 출퇴근 정체를 완화하고, 미래 자율주행 인프라를 마련하기 위한 고시공고입니다. 관련 면허: 정보통신공사업 면허 보유사 우대."
    },
    {
        "title": "{city} 디지털 트윈 기반 문화재 가상 복원 용역",
        "category": "문화/공간정보",
        "department": "문화예술과",
        "budget": 850000000,
        "content": "역사적 가치가 높은 {city} 내 주요 문화유산들을 3D 스캔 및 디지털트윈 모델로 재구축하여, 재난 시 복구 가이드 마련 및 관광 연계 VR 콘텐츠로 활용하기 위한 종합 설계 용역입니다."
    },
    {
        "title": "{city} 2026년도 소상공인 디지털 전환 및 온라인 마케팅 지원 계획",
        "category": "소상공인/경제",
        "department": "일자리경제과",
        "budget": 1200000000,
        "content": "{city} 관내 소상공인 500개 점포를 대상으로 키오스크, 스마트 테이블 오더, AI 고객 분석 솔루션을 보급하고 현장 컨설팅을 지원할 전문 수행 기관을 모집합니다."
    },
    {
        "title": "{city} 청년 창업 활성화 및 R&D 기술 실증 지원 사업",
        "category": "창업/R&D",
        "department": "미래산업혁신본부",
        "budget": 1500000000,
        "content": "지역 내 유망 딥테크 청년 스타트업을 선발하여 {city} 내 공공 인프라를 테스트베드로 무상 제공하고, 시제품 제작 및 특허 실증에 필요한 R&D 비용을 직접 매칭 지원합니다."
    }
]

class PolicyDatabase:
    """수집된 지자체 정책 및 뉴스를 저장하기 위한 로컬 SQLite 데이터베이스 관리 클래스"""
    def __init__(self, db_path: str = "data/nara.db"):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self._init_table()

    def _init_table(self):
        """테이블 초기화"""
        with self.conn:
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS municipal_policies (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    region TEXT NOT NULL,
                    title TEXT NOT NULL,
                    category TEXT,
                    department TEXT,
                    budget INTEGER,
                    content TEXT,
                    keywords TEXT,
                    ai_summary TEXT,
                    relevance_score REAL DEFAULT 0.0,
                    collected_at TEXT,
                    metadata TEXT,
                    UNIQUE(region, title)
                )
            """)
            logger.info("Database table 'municipal_policies' initialized.")

    def save_policies(self, policies: List[Dict]):
        """수집된 정책 데이터를 일괄 삽입/갱신합니다."""
        inserted = 0
        with self.conn:
            for p in policies:
                self.conn.execute("""
                    INSERT OR REPLACE INTO municipal_policies 
                    (region, title, category, department, budget, content, keywords, ai_summary, relevance_score, collected_at, metadata)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    p["region"],
                    p["title"],
                    p["category"],
                    p["department"],
                    p["budget"],
                    p["content"],
                    json.dumps(p.get("keywords", []), ensure_ascii=False),
                    p.get("ai_summary", ""),
                    p.get("relevance_score", 0.0),
                    p["collected_at"],
                    json.dumps(p.get("metadata", {}), ensure_ascii=False)
                ))
                inserted += 1
        logger.info(f"Successfully saved {inserted} policy records to database.")

    def get_all_policies(self) -> List[sqlite3.Row]:
        """저장된 전체 정책을 불러옵니다."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM municipal_policies ORDER BY id DESC")
        return cursor.fetchall()

    def close(self):
        self.conn.close()

def run_collector_pipeline():
    """모의 수집 실행 엔진"""
    logger.info("Starting Policy Collector Pipeline...")
    
    db = PolicyDatabase()
    collected_data = []
    current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 전국 지자체 및 뉴스 수집 데이터 생성
    for region in MUNICIPALITIES:
        logger.info(f"Scanning municipal portal & RSS for [{region}]...")
        for template in POLICY_TEMPLATES:
            title = template["title"].format(city=region)
            content = template["content"].format(city=region)
            
            # 가상 메타데이터 생성
            meta = {
                "source_url": f"https://www.{region.replace('특별시','').replace('광역시','').replace('특별자치도','').replace('도','')}.go.kr/gosi/view",
                "officer_contact": "02-120" if "서울" in region else "031-120" if "경기" in region else "051-120",
                "attachment_files": ["2026_과업지시서.pdf", "신청서식.hwp"]
            }

            collected_data.append({
                "region": region,
                "title": title,
                "category": template["category"],
                "department": template["department"],
                "budget": template["budget"],
                "content": content,
                "collected_at": current_time,
                "metadata": meta
            })

    db.save_policies(collected_data)
    
    # 결과 요약
    all_records = db.get_all_policies()
    logger.info(f"Pipeline complete. Total records in database: {len(all_records)}")
    db.close()

if __name__ == "__main__":
    run_collector_pipeline()
