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

# Create non-root user with a real HOME so HuggingFace / FastMCP caches resolve.
RUN addgroup --system mcp && \
    adduser --system --ingroup mcp --home /home/mcp mcp && \
    mkdir -p /data && chown mcp:mcp /data && \
    mkdir -p /home/mcp/.cache && \
    mv /root/.cache/huggingface /home/mcp/.cache/huggingface && \
    chown -R mcp:mcp /home/mcp

USER mcp

# Default env for Docker
ENV HOME=/home/mcp \
    HF_HOME=/home/mcp/.cache/huggingface \
    TRANSFORMERS_CACHE=/home/mcp/.cache/huggingface \
    TRANSPORT=http \
    HOST=0.0.0.0 \
    CQ_LOCAL_DB_PATH=/data/stolperstein.db

EXPOSE 8716

# Unauthenticated /health returns 200 when the server is up and migrations
# have finished. No bearer token needed → healthcheck logs don't flood
# with 401s.
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD python3 -c "import urllib.request,sys; \
urllib.request.urlopen('http://localhost:8716/health', timeout=3); sys.exit(0)"

CMD ["mcp-stolperstein"]
