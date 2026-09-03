FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    # Chromium runtime libs for Playwright WYSIWYG export (WhatsApp PDF)
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    libpango-1.0-0 \
    libcairo2 \
    fonts-liberation \
    fonts-unifont \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && playwright install chromium

COPY app ./app
COPY static ./static
COPY standalone ./standalone
COPY templates ./templates
COPY strategy-reports ./strategy-reports

ENV HUB_ROOT=/app
ENV DATA_ROOT=/data
ENV HOST=0.0.0.0
ENV PORT=8000

EXPOSE 8000

# Single worker on the 4GB droplet — 2 workers caused OOM kills (502s).
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers ${UVICORN_WORKERS:-1}"]


