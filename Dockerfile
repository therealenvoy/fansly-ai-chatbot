FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --requirement requirements.txt

COPY alembic.ini .
COPY migrations ./migrations
COPY config ./config
COPY src ./src

# Railway volumes are mounted as root. Keep the runtime user compatible with
# /data while the production database itself remains PostgreSQL.
RUN mkdir -p /data

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.getenv('PORT','8080')+'/ready',timeout=3)"

CMD ["python", "-m", "src.main"]
