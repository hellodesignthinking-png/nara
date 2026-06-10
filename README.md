# 🏛️ NARA Analyzer — 나라장터 용역 자동 분석 시스템

나라장터에서 매일 새로 등록되는 용역 공고를 자동으로 수집·분석하고,
**등록된 여러 사업자 중 최적의 사업자를 매칭**하여,
과거 낙찰 데이터 및 관련 기사를 종합한 **AI 기반 입찰 전략 보고서**를 자동 생성합니다.

---

## ✨ 핵심 기능

| 기능 | 설명 |
|------|------|
| 📝 **공고 자동 수집** | 나라장터 API로 매일 새 용역 공고를 수집 |
| 🏢 **다중 사업자 관리** | 여러 사업자를 등록하고 공고별 최적 매칭 |
| 🔍 **과거 데이터 분석** | 2~3년 낙찰 정보 + 발주처 관련 기사 수집 |
| 🤖 **AI 전략 수립** | LLM 기반 입찰 전략 보고서 자동 생성 |
| 📨 **알림 전송** | CLI / 이메일 / Slack으로 분석 결과 전송 |

---

## 🚀 빠른 시작

### 1. 환경 설정

```bash
# 저장소 클론 후 디렉터리 이동
cd nara

# 가상환경 생성 및 활성화
python -m venv .venv
source .venv/bin/activate  # macOS/Linux

# 의존성 설치
pip install -e .

# 환경변수 설정
cp .env.example .env
# .env 파일을 열어 API 키들을 입력하세요
```

### 2. API 키 발급

| API | 발급처 | 용도 |
|-----|--------|------|
| 공공데이터포털 | [data.go.kr](https://data.go.kr) | 나라장터 입찰/낙찰 정보 |
| 네이버 검색 | [developers.naver.com](https://developers.naver.com) | 뉴스 기사 수집 |
| OpenAI | [platform.openai.com](https://platform.openai.com) | AI 분석 |

### 3. 사업자 등록

```bash
# 사업자 등록 (대화형)
python -m src.main register

# 사업자 목록 확인
python -m src.main businesses
```

### 4. 실행

```bash
# 오늘의 공고 분석 실행
python -m src.main analyze

# 특정 기간 공고 분석
python -m src.main analyze --from 20260501 --to 20260531

# 매일 자동 실행 (스케줄링)
python -m src.main schedule --time 08:00
```

---

## 📊 출력 예시

```
┌──────────────────────────────────────────────────────────┐
│  🏛️  NARA Analyzer — 일일 분석 보고서  2026-05-31      │
│  총 15건 공고 수집 → 5건 관심 공고 → 3건 전략 보고서    │
└──────────────────────────────────────────────────────────┘

┌────┬───────────────────────┬──────────┬────────┬────────┬──────────┐
│ #  │ 공고명                │ 발주기관 │ 예산   │ 관련도 │ 최적 사업│
├────┼───────────────────────┼──────────┼────────┼────────┼──────────┤
│ 🟢 │ AI 기반 행정 시스템   │ 서울시   │ 5억    │ 92점   │ A사      │
│ 🟡 │ 데이터 분석 컨설팅    │ 경기도   │ 2억    │ 71점   │ B사      │
│ 🔴 │ 마케팅 전략 수립      │ 부산시   │ 1억    │ 45점   │ A사      │
└────┴───────────────────────┴──────────┴────────┴────────┴──────────┘

📋 전략 보고서: AI 기반 행정 시스템 구축 사업
├─ 📊 사업 핵심: 작년 대비 예산 20% 증가, 글로벌 확장 강조
├─ 🏢 경쟁사: 작년 XX업체 92% 투찰률로 수주
├─ 💡 차별화: RFP 신규 조항에 최근 개정법 반영 필요
└─ ⚠️ 주의: 수도권 소재 업체만 참여 가능
```

---

## 📂 프로젝트 구조

```
nara/
├── src/
│   ├── main.py              # 메인 파이프라인
│   ├── config.py            # 설정 관리
│   ├── models/              # 데이터 모델 + SQLite
│   ├── collectors/          # API 데이터 수집
│   ├── parsers/             # HWP/PDF 파싱
│   ├── analyzers/           # AI 분석 + 사업자 매칭
│   └── reporters/           # CLI/이메일/Slack 보고서
├── tests/                   # 테스트 코드
│   ├── conftest.py          # 공통 fixture
│   ├── test_schemas.py
│   ├── test_nlp.py
│   └── ...
├── data/                    # 로컬 DB + 첨부파일
├── Dockerfile               # 도커 빌드
├── docker-compose.yml       # 도커 컴포즈 설정
├── pyproject.toml
├── .env.example
└── README.md
```

---

## 🐳 Docker 배포

```bash
# Docker Compose로 실행
docker-compose up -d

# 로그 확인
docker-compose logs -f

# 중지
docker-compose down

# 이미지 재빌드 후 실행
docker-compose up -d --build
```

---

## 🧪 테스트 실행

```bash
# 전체 테스트 실행
pytest

# 특정 테스트 파일 실행
pytest tests/test_schemas.py -v

# 커버리지 포함
pytest --cov=src --cov-report=term-missing
```

---

## 🌐 API 서버 실행

```bash
# 개발 서버 실행
uvicorn src.api.app:app --reload --port 8000

# 프로덕션 실행
uvicorn src.api.app:app --host 0.0.0.0 --port 8000 --workers 2
```

---

## 📝 라이선스

MIT License
