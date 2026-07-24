FROM python:3.11-slim

WORKDIR /app

# Install system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY . .

# Create data dir for SQLite (or use mounted /data volume)
RUN mkdir -p /data

# Expose port
EXPOSE 8080

# Run bot in polling mode
CMD ["python", "-m", "src.main"]
