# 🏛️ 전국 지자체 정책 및 뉴스 분석 시스템 설계 계획 (Policy Analysis Pipeline)

본 문서는 전국의 모든 지방자치단체(광역 및 기초의회, 시·도·군청)의 고시공고, 정책 및 관련 뉴스를 실시간으로 수집하고 인공지능(NLP) 기술을 활용하여 핵심 사업 기회를 식별하기 위한 파이프라인 구축 아키텍처를 정의합니다.

---

## 1. 아키텍처 개요

지자체 데이터는 비정형 텍스트 비율이 높고 출처가 산재해 있으므로, **비동기 배치 수집**, **데이터 정제**, **자연어 처리(NLP) 분석**, **데이터베이스 저장**, **API 연동**의 5단계 파이프라인을 구축합니다.

```mermaid
graph TD
    A[지자체 RSS / 고시공고 / 뉴스 API] -->|수집 스크립트| B(Celery / Airflow Task)
    B -->|데이터 정제 & 파싱| C[Raw 데이터 백업]
    C -->|NLP 분석 엔진| D{분류 및 요약}
    D -->|KoBERT 분류 / LLM 요약| E[(PostgreSQL JSONB)]
    E -->|FastAPI 라우터| F[프론트엔드 대시보드]
    E -->|알림 서비스| G[Slack / 이메일 알림]
```

---

## 2. 세부 구현 전략

### ① 데이터 수집 (Data Collection)
- **공공데이터포털(data.go.kr) API**: 전국의 자치법규, 고시공고 목록 통합 수집 API 활용.
- **지자체 RSS 피드 및 웹 크롤링**: RSS를 지원하지 않는 지자체의 경우, `BeautifulSoup` 및 `Playwright`를 이용해 공고 고시판을 주기적으로 스크랩.
- **뉴스 데이터**: 네이버/구글 뉴스 검색 API를 통해 지자체명 + 핵심 키워드("스마트시티", "용역", "디지털트윈", "R&D")의 조합으로 실시간 모니터링.

### ② 데이터 정제 및 저장 (Storage)
- **DBMS**: 비정형 데이터(HTML 본문, 첨부파일 파싱 텍스트, 메타데이터) 처리에 유리한 **PostgreSQL**을 주 저장소로 채택하고, 유연한 확장을 위해 **JSONB** 필드를 활용합니다.
- 중복 제거: 공고 고유번호 및 기사 URL 해싱을 통해 중복 삽입을 원천 차단합니다.

### ③ 자연어 처리 및 AI 분석 (NLP & AI Engine)
- **키워드 및 토픽 모델링**: `BERTopic` 또는 `KoNLPy`를 활용하여 지자체별 주요 관심 정책 트렌드를 군집화.
- **KoBERT 분류기**: 수집된 텍스트가 정보통신(ICT), 건설, 보건, 교육 등 어떤 산업 도메인에 속하는지 멀티 라벨 분류(Multi-label Classification).
- **LLM 요약 및 매칭**: GPT-4 또는 로컬 경량 LLM(Llama-3-Ko 등)을 이용해 수집된 방대한 정책 문서를 3줄로 요약하고, 사용자의 관심 등록 키워드와 연관성을 점수화.

### ④ 비동기 파이프라인 스케줄링
- **Celery & Redis**: 무거운 NLP 연산과 크롤링 작업이 웹 서버 응답성에 영향을 주지 않도록 백그라운드 워커에 할당하고, 매시간 실행되도록 스케줄러 세팅.

---

## 3. 추천 인프라 스펙 및 설정 (Docker Compose)

컨테이너 환경에서 DB 및 배치 분석 엔진을 구동하기 위한 통합 인프라 구성 예시입니다.

```yaml
version: '3.8'

services:
  postgres:
    image: postgres:15-alpine
    container_name: nara-postgres
    environment:
      POSTGRES_DB: nara_policy
      POSTGRES_USER: nara_admin
      POSTGRES_PASSWORD: secure_password_here
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
    restart: always

  redis:
    image: redis:7-alpine
    container_name: nara-redis
    ports:
      - "6379:6379"
    restart: always

  celery_worker:
    build: .
    command: celery -A src.scheduler.celery_app worker --loglevel=info
    depends_on:
      - redis
      - postgres
    environment:
      - DATABASE_URL=postgresql://nara_admin:secure_password_here@postgres:5432/nara_policy
      - REDIS_URL=redis://redis:6379/0

volumes:
  pgdata:
```

---

## 4. 수집 및 분석 예제 스크립트 제공

구현을 돕기 위해 실무 수준의 기초 코드를 제공합니다.

- **[수집 스크립트 (collect_policies.py)](file:///Users/TaiNa0/Desktop/nara/scripts/collect_policies.py)**: 전국 지자체의 모의 정책 공고 및 뉴스 리소스를 수집 및 데이터베이스화하는 시뮬레이터.
- **[NLP 분석 스크립트 (run_nlp.py)](file:///Users/TaiNa0/Desktop/nara/scripts/run_nlp.py)**: 자연어 토크나이징, 형태소 분석 및 TF-IDF 기반 핵심 키워드 추출과 AI 요약을 수행하는 분석기.
