# OK-202 PoC image. Pin base image digest and Python dependencies before production.
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    OPENKUBES_MCP_TRANSPORT=streamable-http \
    OPENKUBES_MCP_HOST=0.0.0.0 \
    OPENKUBES_MCP_PORT=8000 \
    OPENKUBES_DOCS_INDEX=/data/index.json
WORKDIR /app
COPY requirements-mcp.txt /app/
RUN python -m pip install --no-cache-dir -r requirements-mcp.txt \
    && useradd --uid 10001 --create-home --shell /usr/sbin/nologin app
COPY indexer.py docs_mcp.py /app/
USER 10001:10001
EXPOSE 8000
CMD ["python", "/app/docs_mcp.py"]
