FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 1000 app \
    && useradd --uid 1000 --gid app --create-home app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY api/ api/
COPY core/ core/
COPY data/ data/
COPY frontend/ frontend/
COPY scripts/ scripts/
COPY scripts/docker-entrypoint.sh /docker-entrypoint.sh
COPY scripts/worker-entrypoint.sh /worker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh /worker-entrypoint.sh \
    && chown -R app:app /app

USER app

EXPOSE 8000

ENTRYPOINT ["/docker-entrypoint.sh"]
