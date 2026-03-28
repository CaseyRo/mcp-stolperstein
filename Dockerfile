FROM python:3.12-slim AS builder

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src/ ./src/

RUN pip install --no-cache-dir .

# Pre-download the embedding model at build time
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

FROM python:3.12-slim

WORKDIR /app

# Copy installed packages and model cache from builder
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin/mcp-stolperstein /usr/local/bin/mcp-stolperstein
COPY --from=builder /root/.cache/huggingface /root/.cache/huggingface
COPY --from=builder /app/src ./src

# Create non-root user
RUN addgroup --system mcp && adduser --system --ingroup mcp mcp && \
    mkdir -p /data && chown mcp:mcp /data && \
    mv /root/.cache/huggingface /home/mcp/.cache/huggingface && \
    chown -R mcp:mcp /home/mcp/.cache

USER mcp

# Default env for Docker
ENV TRANSPORT=http
ENV HOST=0.0.0.0
ENV CQ_LOCAL_DB_PATH=/data/stolperstein.db

EXPOSE 8716

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python3 -c "from urllib.request import urlopen;from urllib.error import HTTPError,URLError;exec('try:\n urlopen(\"http://localhost:8716/mcp\")\nexcept HTTPError:\n pass\nexcept URLError:\n raise')"

CMD ["mcp-stolperstein"]
