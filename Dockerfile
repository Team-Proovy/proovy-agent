FROM python:3.12-slim

# WeasyPrint 의존성 (PDF 생성용)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    libfontconfig1 \
    libcairo2 \
    libgdk-pixbuf-2.0-0 \
    libgtk-3-0 \
    fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# uv 설치
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

# 프로젝트 파일 복사
COPY . .

# 의존성 설치 (lock 파일 기준 고정 설치)
RUN uv sync --frozen

# Cloud Run이 PORT 환경변수를 주입함 (기본 8080)
ENV PORT=8080
EXPOSE 8080

# FastAPI 서버 실행 — Cloud Run이 주는 $PORT 포트로 바인딩
CMD ["sh", "-c", "uv run uvicorn proovy_agent.app.main:app --host 0.0.0.0 --port ${PORT}"]