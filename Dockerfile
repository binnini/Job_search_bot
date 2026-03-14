FROM python:3.11-slim

# 시스템 패키지 (Playwright 브라우저 의존성 포함)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    # Playwright Chromium 의존성
    libnss3 \
    libnspr4 \
    libdbus-1-3 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libxkbcommon0 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.docker.txt .
RUN pip install --no-cache-dir -r requirements.docker.txt

# Playwright Chromium 브라우저 설치 (crawler 서비스에서만 사용)
RUN playwright install chromium

COPY . .

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app
