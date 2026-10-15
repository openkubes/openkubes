# OK-202 PoC image, pinned to the observed Linux/amd64 base digest.
# Exact Python versions are locked; hash lock, scans and provenance remain release gates.
FROM python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    OPENKUBES_MCP_TRANSPORT=streamable-http \
    OPENKUBES_MCP_HOST=0.0.0.0 \
    OPENKUBES_MCP_PORT=8000 \
    OPENKUBES_DOCS_INDEX=/data/index.json
WORKDIR /app
COPY requirements-mcp.lock /app/
RUN python -m pip install --no-cache-dir -r requirements-mcp.lock \
    && useradd --uid 10001 --create-home --shell /usr/sbin/nologin app
COPY indexer.py docs_mcp.py /app/
USER 10001:10001
EXPOSE 8000
CMD ["python", "/app/docs_mcp.py"]
