FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY scripts/ ./scripts/
COPY data/     ./data/
COPY assets/   ./assets/

ENV PYTHONPATH=/app/scripts
ENV PYTHONUNBUFFERED=1

CMD ["python", "scripts/scheduler.py"]
