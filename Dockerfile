# ═══════════════════════════════════════════════
# NARA Analyzer — Dockerfile (멀티스테이지 빌드)
# 나라장터 용역 자동 분석 시스템
# ═══════════════════════════════════════════════

# ── Build Stage ────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

# 의존성만 먼저 설치 (캐시 레이어 활용)
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ── Runtime Stage ──────────────────────────────
FROM python:3.12-slim AS runtime

# 시스템 의존성 (한글 지원)
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

# 빌드 스테이지에서 설치된 패키지 복사
COPY --from=builder /install /usr/local

# 비루트 사용자 생성 및 전환
RUN useradd --create-home --shell /bin/bash nara

WORKDIR /app

# 소스 코드 복사
COPY src/ src/
COPY static/ static/

# 데이터 디렉터리 생성 + settings 복사
RUN mkdir -p data && chown -R nara:nara /app
COPY --chown=nara:nara data/settings.json data/settings.json

# 비루트 사용자로 전환
USER nara

# 포트 노출
EXPOSE 8000

# 환경변수 기본값 (런타임에 오버라이드)
ENV SCHEDULER_ENABLED=true \
    SCHEDULE_HOUR=8 \
    SCHEDULE_MINUTE=0

# 헬스체크
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request,os; urllib.request.urlopen(f'http://localhost:{os.environ.get(\"PORT\",8000)}/health')" || exit 1

# 실행
CMD ["/bin/sh", "-c", "uvicorn src.api.app:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
