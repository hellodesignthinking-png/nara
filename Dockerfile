# ═══════════════════════════════════════════════
# NARA Analyzer — Dockerfile
# 나라장터 용역 자동 분석 시스템
# ═══════════════════════════════════════════════

FROM python:3.12-slim AS base

# 시스템 의존성 (한글 지원 + 빌드 도구)
RUN apt-get update && apt-get install -y --no-install-recommends \
    locales \
    && sed -i '/ko_KR.UTF-8/s/^# //g' /etc/locale.gen \
    && locale-gen ko_KR.UTF-8 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

ENV LANG=ko_KR.UTF-8 \
    LC_ALL=ko_KR.UTF-8 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# 의존성 설치 (캐시 레이어 활용)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 소스 코드 복사
COPY src/ src/
COPY static/ static/

# 데이터 디렉터리 생성
RUN mkdir -p data

# 포트 노출
EXPOSE 8000

# 환경변수 기본값 (런타임에 오버라이드)
ENV SCHEDULER_ENABLED=true \
    SCHEDULE_HOUR=8 \
    SCHEDULE_MINUTE=0

# 헬스체크
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/dashboard/stats')" || exit 1

# 실행 (Gunicorn + Uvicorn 워커)
CMD ["uvicorn", "src.api.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
